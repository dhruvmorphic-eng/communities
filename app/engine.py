"""Discovery is demand-driven, cached for a day, and optionally refreshed while running."""
import concurrent.futures
import datetime
import hashlib
import itertools
import json
import re
import threading
import time
import urllib.parse
import storage
import experiments
from webfetch import company_pages, fetch_page, normalize_url, search_web, search_provider
from intelligence import canonical, explain, extract_community, profile_company, retrieve, refine_profile, platform_key

DISCOVERY_LOCK=threading.Lock()
WORKERS=concurrent.futures.ThreadPoolExecutor(max_workers=2)

def identity_match(record,records):
    urls={canonical(record.get(k)) for k in ['source_url','official_url','join_url'] if record.get(k)}
    for old in records:
        oldurls={canonical(old.get(k)) for k in ['source_url','official_url','join_url'] if old.get(k)}
        # A shared generic platform homepage is not identity evidence.
        shared={u for u in urls & oldurls if u not in ['discord.com/','slack.com/','facebook.com/','linkedin.com/']}
        if shared:return old
    # A brand may use /, /community and /join for the same named community.
    # Require both the same name and the same non-platform host; names alone are ambiguous.
    name=re.sub(r'[^a-z0-9]','',str(record.get('name','')).lower())
    def branded_hosts(r):
        hosts=set()
        for k in ['source_url','official_url','join_url']:
            host=(urllib.parse.urlsplit(r.get(k) or '').hostname or '').removeprefix('www.')
            if host and host not in ['thehiveindex.com','discord.com','discord.gg','slack.com','join.slack.com','facebook.com','linkedin.com','reddit.com','t.me','chat.whatsapp.com']:
                hosts.add(host)
        return hosts
    hosts=branded_hosts(record)
    if name and hosts:
        for old in records:
            if re.sub(r'[^a-z0-9]','',old.get('name','').lower())==name and hosts & branded_hosts(old):return old
    return None

def merge_record(record,old):
    record={**record,'community_id':old['community_id']}
    record['topics']=list(dict.fromkeys(old['topics']+record['topics']))
    record['sources']=old.get('sources',[])+record.get('sources',[])
    for k in ['vendor_eligible','selling_allowed','research_survey_allowed']:
        if old.get(k) is False:record[k]=False
    if old.get('commercial_policy') and not record.get('commercial_policy'):
        record['commercial_policy']=old['commercial_policy'];record['policy_recheck_needed']=True
    for k in ['commercial_options','opportunity_area','directory_policy_warning','access_note']:
        if old.get(k) and not record.get(k):record[k]=old[k]
    if not record.get('join_url') and old.get('join_url'):
        record['join_url']=old['join_url'];record['join_url_status']='previously_observed_not_rechecked'
    return record

def ingest(doc,settings,topics,origin='discovered',existing=None):
    record=extract_community(doc,settings,topics)
    if not record:return {'status':'skipped','url':doc['url'],'reason':'A single relevant recurring community was not established.'}
    old=existing or identity_match(record,storage.all_communities())
    if not old:
        same_name=[r for r in storage.all_communities() if re.sub(r'[^a-z0-9]','',r['name'].lower())==re.sub(r'[^a-z0-9]','',record['name'].lower())]
        if same_name:
            storage.observe(None,doc['url'],'identity_review',{'candidate':record,'possible_existing_ids':[r['community_id'] for r in same_name]})
            return {'status':'needs_review','name':record['name'],'url':doc['url'],'reason':'A community with this name already exists, but shared identity is unconfirmed. Saved for identity review rather than counted as new.'}
    if old:
        # A new page may omit an older rule. Silence cannot remove an established prohibition.
        record=merge_record(record,old)
    added=storage.put_community(record,origin)
    storage.observe(record['community_id'],doc['url'],'retrieved',{'method':doc['method'],'community_evidence_quote':record.get('community_evidence_quote'),'extraction_mode':record['extraction_mode']})
    return {'status':'added' if added else 'updated','community_id':record['community_id'],'name':record['name'],'url':doc['url']}

def discover(profile,settings,force=False,progress=lambda _:None):
    provider=search_provider(settings)
    if not provider:
        return {'status':'unconfigured','added':0,'updated':0,'queries':[],'events':[],'message':'Live discovery needs Claude web search, Firecrawl or Exa. You can still add a community URL below.'}
    topics=profile.get('buyer_topics',[])[:2] or profile.get('practitioner_topics',[])[:2]
    if not topics:return {'status':'no_topics','added':0,'updated':0,'queries':[],'events':[]}
    queries=profile.get('search_queries',[])[:2] or [f'"{t.replace("-"," ")}" community join Slack Discord forum professional' for t in topics]
    key=hashlib.sha256(json.dumps([provider,queries]).encode()).hexdigest()
    with DISCOVERY_LOCK:
        cached=storage.cache_discovery(key)
        if cached and not force:return {**cached,'status':'cached','message':'Using discovery completed within the past 24 hours. Refresh now to search again.'}
        progress('Searching the web for new communities')
        events=[];found=[];batches=[];search_success=0
        for q in queries:
            try:batches.append(search_web(q,settings));search_success+=1
            except Exception as e:events.append({'status':'error','query':q,'reason':str(e)})
        # Give both buyer searches a chance before spending the bounded page budget.
        found=[row for group in itertools.zip_longest(*batches) for row in group if row] if batches else []
        def page_priority(row):
            parsed=urllib.parse.urlsplit(row.get('url',''));path=parsed.path.lower();title=row.get('title','').lower()
            score=0
            if re.search(r'(?:community|forum|membership|join)(?:/|$)|slack-community',path):score+=4
            if re.search(r'\b(community|forum|membership)\b',title):score+=3
            if re.search(r'/(blog|articles?|resources?|posts?|insights|learn)/',path) or (parsed.hostname or '').startswith('blog.') or parsed.hostname=='medium.com':score-=8
            if re.search(r'\b(?:best|top|\d+)\b.*\b(communities|groups|channels)\b',title):score-=8
            if re.search(r'/(topics|category|platforms)/',path):score-=8
            return score
        found=sorted(found,key=page_priority,reverse=True)
        existing=storage.all_communities();seen=set();targets=[]
        for row in found:
            try:u=normalize_url(row['url'])
            except ValueError:continue
            host=urllib.parse.urlsplit(u).hostname
            if host.endswith(('youtube.com','tiktok.com')):continue
            if canonical(u) in seen:continue
            seen.add(canonical(u))
            if identity_match({'source_url':u},existing):continue
            targets.append(u)
        progress('Checking new community pages')
        def check(url):
            try:return ingest(fetch_page(url,settings,True),settings,topics)
            except Exception as e:
                storage.observe(None,url,'failed',{'error':str(e)})
                return {'status':'error','url':url,'reason':str(e)}
        with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
            events+=list(pool.map(check,targets[:3]))
        result={'status':'completed' if search_success else 'failed','provider':provider,'checked_at':storage.now(),'added':sum(e['status']=='added' for e in events),'updated':sum(e['status']=='updated' for e in events),'queries':queries,'search_results':len(found),'search_hits':[{'url':r.get('url'),'title':r.get('title','')} for r in found],'candidate_pages_considered':len(targets),'page_budget':3,'events':events}
        if search_success:storage.cache_discovery(key,result)
        return result

def refresh_candidates(ranked,settings,progress=lambda _:None):
    events=[];due=[]
    for row in ranked:
        r=row['record'];date=r.get('last_live_checked_at')
        if date:
            try:
                checked=datetime.datetime.fromisoformat(date.replace('Z','+00:00')).timestamp()
                if time.time()-checked<7*86400:continue
            except ValueError:pass
        # Prefer an official page when its actual URL is known.
        u=r.get('official_url') or r.get('join_url') or r.get('listing_url')
        if u and '/topics/' not in u:due.append((r,u))
        if len(due)>=2:break
    if due:progress('Refreshing sources for likely recommendations')
    for r,u in due:
        try:events.append(ingest(fetch_page(u,settings,True),settings,r['topics'],origin='refreshed',existing=r))
        except Exception as e:
            storage.observe(r['community_id'],u,'failed',{'error':str(e)})
            events.append({'status':'error','name':r['name'],'url':u,'reason':str(e)})
    return events

def analyze_company(body,progress=lambda _:None):
    settings=storage.settings();url=normalize_url(body.get('url',''))
    goal=body.get('goal','customers')
    if goal not in ['customers','partners','feedback','traction']:raise ValueError('Choose a valid goal.')
    context=str(body.get('context',''))[:2000]
    progress('Reading your website and product pages')
    docs,warnings=company_pages(url,settings)
    progress('Understanding your offer and target buyers')
    # Fail visibly if a configured AI provider fails. Do not silently fake AI output.
    profile,profile_warnings=profile_company(docs,goal,context,settings);warnings+=profile_warnings
    storage.save_profile(profile['domain'],profile)
    return {'kind':'analysis','profile':profile,'warnings':warnings,'sources_read':[{'url':d['url'],'title':d['title'],'method':d['method']} for d in docs]}

PLATFORMS=['all','slack','discord','reddit','facebook','linkedin','whatsapp','telegram','forums','other']

def recommend(body,progress=lambda _:None):
    settings=storage.settings();platform=body.get('platform','all')
    if platform not in PLATFORMS:raise ValueError('Choose a supported community platform.')
    limit=body.get('limit',18)
    if isinstance(limit,bool) or not isinstance(limit,int) or not 1<=limit<=24:raise ValueError('Choose between 1 and 24 recommendations.')
    if body.get('analysis_id'):
        analysis=storage.get_job(str(body['analysis_id']))
        if not analysis or analysis['status']!='completed' or (analysis.get('result') or {}).get('kind')!='analysis':raise ValueError('Analyze your website before finding communities.')
        analysis=analysis['result'];goal=body.get('goal',analysis['profile']['goal'])
        if goal not in ['customers','partners','feedback','traction']:raise ValueError('Choose a valid goal.')
        progress('Applying your company brief')
        profile=refine_profile(analysis['profile'],body.get('profile_edits',{}),goal,settings)
        warnings=list(analysis.get('warnings',[]));sources=analysis['sources_read']
    else:
        analysis=analyze_company(body,progress);profile=analysis['profile'];warnings=analysis['warnings'];sources=analysis['sources_read']
    storage.save_profile(profile['domain'],profile)
    discovery_profile={**profile}
    queries=profile.get('search_queries',[])[:2] or [profile['buyer_description'][:130]+' professional community join']
    if platform!='all':queries=[q+' '+('professional forum' if platform=='forums' else platform)+' community join' for q in queries]
    discovery_profile['search_queries']=queries
    discovery=discover(discovery_profile,settings,force=body.get('force_discovery') is True,progress=progress)
    if discovery['status']=='unconfigured':warnings.append(discovery['message'])
    if discovery['status']=='failed':warnings.append('Live discovery failed. Existing catalog candidates are still available; inspect the research log.')
    feedback=storage.feedback_for(profile['domain'])
    ranked,exclusions=retrieve(profile,storage.all_communities(),feedback)
    counts={key:sum(platform_key(x['record']['platform'])==key for x in ranked) for key in PLATFORMS if key!='all'}
    if platform!='all':ranked=[x for x in ranked if platform_key(x['record']['platform'])==platform]
    refresh=refresh_candidates(ranked,settings,progress)
    if any(e['status']=='error' for e in refresh):warnings.append('Some source refreshes failed. Those results retain older evidence and show their previous evidence dates.')
    progress('Ranking communities and writing reasons')
    ranked,exclusions=retrieve(profile,storage.all_communities(),feedback)
    counts={key:sum(platform_key(x['record']['platform'])==key for x in ranked) for key in PLATFORMS if key!='all'}
    if platform!='all':ranked=[x for x in ranked if platform_key(x['record']['platform'])==platform]
    assignment=experiments.assign(body['experiment_participant']) if body.get('experiment_participant') else None
    if assignment and assignment['ranking']=='evidence_first':
        recommendations=explain(profile,ranked,settings,limit,strategy='evidence_first')
    else:recommendations=explain(profile,ranked,settings,limit)
    storage.save_profile(profile['domain'],profile,discovered=discovery['status'] in ['completed','cached'])
    return {'experiment':{**assignment,'ranking_applied':bool(settings.get('ai_key') and ranked)} if assignment else None,'kind':'recommendations','profile':profile,'recommendations':recommendations,'platform':platform,'platform_counts':counts,'catalog_matches':len(ranked),'warnings':warnings,'discovery':discovery,'refresh':refresh,'excluded':exclusions,'catalog':storage.stats(),'created_at':storage.now(),'coverage_note':f'{len(recommendations)} research candidates found. Eligibility and permission to promote must be checked before participating.','sources_read':sources}

def run_job(jid,kind,body):
    def progress(stage):storage.update_job(jid,stage)
    try:
        if kind=='analyze':
            result=analyze_company(body,progress);result['analysis_id']=jid
        elif kind=='recommend':result=recommend(body,progress)
        elif kind=='add':
            progress('Reading the community page')
            settings=storage.settings();doc=fetch_page(normalize_url(body.get('url','')),settings,True)
            result=ingest(doc,settings,[],origin='submitted')
            result['catalog']=storage.stats()
        elif kind=='refresh':
            profiles=storage.due_profiles()
            if body.get('domain'):
                with storage.connection() as c:row=c.execute('SELECT payload FROM profiles WHERE domain=?',(body['domain'],)).fetchone()
                profiles=[json.loads(row['payload'])] if row else []
            results=[discover(p,storage.settings(),force=True,progress=progress) for p in profiles[:3]]
            for p,r in zip(profiles,results):
                if r['status'] in ['completed','cached']:storage.save_profile(p['domain'],p,True)
            result={'runs':results,'catalog':storage.stats(),'message':'No saved company profiles to refresh.' if not profiles else 'Discovery pass finished. Run recommendations again to use updated candidates.'}
        else:raise ValueError('Unknown job type.')
        result['job_id']=jid
        if body.get('experiment_participant'):
            result['experiment_participant']=experiments.identifier(body['experiment_participant'])
            result['experiment_flow']=experiments.identifier(body.get('experiment_flow'))
        storage.update_job(jid,'Complete','completed',result=result)
    except Exception as e:storage.update_job(jid,'Stopped','failed',error=str(e)[:600])

def submit(kind,body):
    if body.get('experiment_participant'):
        experiments.identifier(body['experiment_participant']);experiments.identifier(body.get('experiment_flow'))
    jid=storage.create_job(kind);WORKERS.submit(run_job,jid,kind,body);return jid

def background_loop():
    # This is app functionality, not a system cron or a Codex automation.
    while True:
        time.sleep(3600)
        settings=storage.settings()
        if not settings.get('background_refresh') or not search_provider(settings):continue
        for p in storage.due_profiles():
            try:
                result=discover(p,settings)
                if result['status'] in ['completed','cached']:storage.save_profile(p['domain'],p,True)
            except Exception:pass
