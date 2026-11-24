"""Compact display projections; structured tool results remain intact."""
import json

def session_summary(content):
    if isinstance(content, str):
        try: content = json.loads(content)
        except (ValueError, TypeError): return content
    if not isinstance(content, dict): return str(content)
    if "duts" in content:
        return "\n".join(f"{row['dut_name']} | {row['kind']} | {row['source_workspace']}" for row in content["duts"]) or "No DUT sources found; specify a source_workspace inside configured roots."
    if "workflows" in content:
        return "\n".join(f"{w['workflow_ref']} | {w['purpose']}" +
                         (f" | unavailable: {w['unavailable']}" if w.get("unavailable") else "")
                         for w in content["workflows"]) or "No workflows available."
    if content and all(isinstance(p, dict) and "backend" in p for p in content.values()):
        return "\n".join(f"{name} | {p['backend']} | max Subs: {p.get('max_subagents', 1)}" for name, p in content.items())
    if "agents" in content:
        return "\n".join(f"{a['agent_id']} | {a['status']} | {a.get('dut_name', '')} / {a.get('workflow_ref', '')}" for a in content["agents"]) or "No Super agents yet."
    if "agent_id" in content:
        return f"{content['agent_id']} | {content.get('status', '')} | attempt {content.get('attempt', 1)}" + (f"\n{content['error']}" if content.get('error') else "")
    return json.dumps(content, ensure_ascii=False, default=str)[:4000]
