"""Exercise the running app with real providers. Uses configured keys; never prints them.

Run: python3 live_flow_test.py
This makes paid API calls when both providers are configured.
Results are saved to live-flow-results.json for human relevance review.
"""
import argparse
import json
from pathlib import Path
import time
import urllib.request

BASE = 'http://127.0.0.1:8765'
CASES = [
    ('cnvrted', 'https://cnvrted.com', 'B2B revenue, sales and growth teams; distinguish buyers from AI hobbyists.'),
    ('buffer', 'https://buffer.com', 'Social media practitioners, creators and small business marketers.'),
    ('gusto', 'https://gusto.com', 'Small business owners, people/HR teams and accounting partners; distinguish US payroll fit from generic business groups.'),
]


def api(path, body=None, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['X-CSRF-Token'] = token
    req = urllib.request.Request(BASE + path, headers=headers,
                                 data=json.dumps(body).encode() if body is not None else None)
    with urllib.request.urlopen(req, timeout=30) as response:
        return json.load(response)


def run(output, cases=None):
    status = api('/api/status')
    settings = status['settings']
    report = {'started_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
              'catalog_before': status['catalog'], 'provider_status': settings, 'cases': []}

    def save():
        output.write_text(json.dumps(report, indent=2) + '\n')

    search_ready=settings['firecrawl_key'] or settings['exa_key'] or (settings['ai_provider']=='anthropic' and settings['ai_key'] and settings['model'])
    if not (settings['ai_key'] and settings['model'] and search_ready):
        report['status'] = 'blocked_missing_provider_configuration'
        save()
        print('Blocked: configure an AI provider and live search (Claude web search, Firecrawl or Exa).', flush=True)
        return 2

    for name, url, review_focus in CASES:
        if cases and name not in cases:continue
        case = {'name': name, 'url': url, 'review_focus': review_focus}
        report['cases'].append(case)
        # No target-audience hints: the app must infer the business from its website.
        jid = api('/api/jobs', {'kind': 'recommend', 'url': url,
                              'goal': 'customers', 'force_discovery': True}, status['csrf_token'])['job_id']
        case['job_id'] = jid
        save()
        deadline, last_stage = time.monotonic() + 1500, None
        while time.monotonic() < deadline:
            job = api('/api/jobs/' + jid)
            if job['stage'] != last_stage:
                print(f"{name}: {job['stage']}", flush=True)
                last_stage = job['stage']
            if job['status'] in ('completed', 'failed'):
                case['job'] = job
                result = job.get('result') or {}
                case['checks'] = {
                    'completed': job['status'] == 'completed',
                    'ai_profile': result.get('profile', {}).get('mode') == 'ai',
                    'fresh_discovery': result.get('discovery', {}).get('status') == 'completed',
                    'recommendation_count': len(result.get('recommendations', [])),
                    'new_community_count': result.get('discovery', {}).get('added', 0),
                    'human_relevance_review': 'pending',
                }
                save()
                break
            time.sleep(5)
        else:
            case['status'] = 'timed_out_job_may_still_be_running'
            save()
            return 1
    report['catalog_after'] = api('/api/status')['catalog']
    report['status'] = 'completed_pending_human_review'
    save()
    print(f'Results saved: {output}', flush=True)
    return 0 if all(c['checks']['completed'] for c in report['cases']) else 1


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path(__file__).with_name('live-flow-results.json'))
    parser.add_argument('--cases',nargs='+',choices=[c[0] for c in CASES],help='Rerun only selected businesses.')
    args = parser.parse_args()
    raise SystemExit(run(args.output,args.cases))
