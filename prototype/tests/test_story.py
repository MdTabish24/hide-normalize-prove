"""The story is a separate operator view; no live evaluation in these tests."""
import json
from pathlib import Path

from fastapi.testclient import TestClient
import pytest

from dashboard.app import create_app
from dashboard.story import snapshot, timing_verdict, validity


def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data), encoding="utf-8")


def test_new_route_does_not_replace_old_dashboard(tmp_path):
    client = TestClient(create_app(saved=tmp_path,runtime=tmp_path))
    old = client.get("/").text
    assert "What Red sees" in old and 'src="/static/app.js"' in old
    story = client.get("/story").text
    assert 'src="/static/scenes.js"' in story and 'src="/static/story.js"' in story
    assert '<table' not in story and 'href="/story/evidence"' in story
    assert 'https://' not in story
    assert client.get("/static/story.css").status_code == 200


def test_missing_data_is_incomplete(tmp_path):
    value = snapshot(tmp_path,tmp_path)
    assert not value["requests"] and value["validity"]["status"] == "INCOMPLETE"
    assert value["checks"] == dict(isolation="NOT RUN",timing="NOT RUN",audit="NOT RUN")
    assert value["matrix"]["saved"] == 0


@pytest.mark.parametrize("args,status",[
    ((.5,4,[.15,.85]),"NOT RUN"),((.98,200,[.95,.99]),"LEAKED"),
    ((.5,200,[.43,.57]),"NO LEAK FOUND"),((.565,200,[.496,.632]),"BOUNDED LEAK"),
    ((.5,200,[-1,2]),"NOT RUN"),((None,None,None),"NOT RUN")])
def test_timing_rules(args,status):
    assert timing_verdict(*args)["status"] == status


@pytest.mark.parametrize("inputs,status",[
    (("PASS","NO LEAK FOUND","VALID"),"VALID"),
    (("PASS","LEAKED","VALID"),"INVALID"),
    (("FAIL","BOUNDED LEAK","VALID"),"INVALID"),
    (("PASS","BOUNDED LEAK","INVALID"),"INVALID"),
    (("NOT RUN","NO LEAK FOUND","VALID"),"INCOMPLETE"),
    (("FAIL","NOT RUN","VALID"),"INCOMPLETE")])
def test_validity_does_not_invent_missing_checks(inputs,status):
    assert validity(*inputs)["status"] == status


def test_secret_fields_never_served_and_reports_correlate(tmp_path):
    secret="BLUE_SECRET_CANARY_7391 pineapple mango sk-private-key"
    write(tmp_path / "story.json",dict(recorded_at=123,policy="window_hard",prompt=secret,
        requests=[dict(index=1,run=1,probe="A-family probe",world=0,allowed=0,status=202,
                       body_length=64,response="pending",total=.9,envelope_exact=True,model_output=secret,filter=secret)],
        runs=[dict(index=1,evaluation=dict(attempts=2,safe=1,cancelled=0,key=secret),
                   report=dict(safe_range=[0,2],budget_left=0,repeat_equal=True,third_pending=True,token=secret),
                   audit=dict(status="VALID",count=13,signing_key=secret))]))
    value=snapshot(tmp_path,tmp_path)
    for word in secret.split():
        assert word not in json.dumps(value)
    assert value["requests"][0]["run"] == value["runs"][0]["index"]
    assert value["runs"][0]["report"]["safe_range"] == [0,2]
    assert value["requests"][0]["output_contained"] is True
    assert value["requests"][0]["model_recorded"] is False
    assert value["runs"][0]["validity"]["status"] == "INCOMPLETE"


def test_global_old_report_not_attached_to_each_request(tmp_path):
    write(tmp_path / "state.json",dict(requests=[dict(index=1,status=202,body_length=64,response="pending",allowed=1)],
        report=dict(safe_range=[0,1],budget_left=0),accuracy=dict(n=4,correct=2)))
    value=snapshot(tmp_path,tmp_path)
    assert value["source"] == "previous demo" and value["runs"] == []
    assert value["requests"][0]["output_contained"] is None
    assert value["checks"]["timing"] == "NOT RUN"


def test_evidence_labels_raw_and_deduplicates_agents(tmp_path):
    rows=[dict(test="Timing A-vs-B: ordinary",policy="raw",result="LEAKED",audit_mode="on")]
    rows += [dict(test="External coding-agent red team",policy=p,result="NOT RUN",audit_mode="on")
             for p in ("raw","bucket_hard","window_hard")]
    write(tmp_path / "evidence/results.json",dict(rows=rows))
    value=snapshot(tmp_path,tmp_path)
    assert value["evidence"][0]["status"] == "Baseline (no defense): leaked"
    assert value["evidence"][0]["audit_mode"] == "on"
    assert len([r for r in value["evidence"] if r["test"] == "External coding-agent red team"]) == 1


def test_story_http_boundary_is_allowlisted(tmp_path):
    runtime=tmp_path / "runtime"
    write(runtime / "observations/story.json",dict(recorded_at=1,policy="raw",requests=[],runs=[],api_key="hidden"))
    client=TestClient(create_app(saved=tmp_path,runtime=runtime,eval_mode=False))
    response=client.get("/api/story")
    assert response.status_code == 200 and "hidden" not in response.text
    assert response.json()["test_only"] is False
    assert client.get("/api/red").json() == {"requests":[]}


def test_windows_reader_lock_does_not_kill_worker(tmp_path,monkeypatch):
    from dashboard.recording import atomic_json
    original = Path.replace
    calls=[]
    def busy_then_ok(self,target):
        calls.append(1)
        if len(calls)<3:
            raise PermissionError("simulated Windows reader")
        return original(self,target)
    monkeypatch.setattr(Path,"replace",busy_then_ok)
    monkeypatch.setattr("dashboard.recording.time.sleep",lambda _:None)
    assert atomic_json(tmp_path / "state.json",{"status":"idle"})
    assert len(calls)==3 and json.loads((tmp_path / "state.json").read_text()) == {"status":"idle"}
    monkeypatch.setattr(Path,"replace",lambda *args: (_ for _ in ()).throw(PermissionError()))
    assert atomic_json(tmp_path / "state.json",{"status":"new"}) is False
    assert json.loads((tmp_path / "state.json").read_text()) == {"status":"idle"}


def test_actor_events_are_allowlisted_and_old_service_state_is_unknown(tmp_path):
    secret="BLUE_SECRET_CANARY_7391 pineapple sk-private-key"
    write(tmp_path / "story.json",dict(recorded_at=1,environment="running",events=[
        dict(kind="sent",seq=1,index=1,run=1,probe="A-family probe",prompt=secret,token=secret),
        dict(kind="decision",seq=2,index=1,run=1,probe=secret,output=secret),
        dict(kind=secret,seq=3)],requests=[],runs=[]))
    result=snapshot(tmp_path,tmp_path)
    assert result["environment"] == "unknown"  # No fresh worker heartbeat.
    assert [e["kind"] for e in result["events"]] == ["sent","decision"]
    assert result["events"][1]["probe"] is None
    for word in secret.split():
        assert word not in json.dumps(result)


def test_robot_stage_has_named_roles_and_explicit_replay(tmp_path):
    client=TestClient(create_app(saved=tmp_path,runtime=tmp_path))
    page=client.get("/story").text
    for label in ("Two synchronized evidence panels","Client LLM","private guard",
                  "duel-before","duel-after","Scenario"):
        assert label in page
    assert client.get("/static/stage.js").status_code == 200
    assert client.get("/static/stage.css").status_code == 200


def test_simple_view_has_live_run_and_two_playback_controls(tmp_path):
    from html.parser import HTMLParser
    class Controls(HTMLParser):
        def __init__(self):
            super().__init__(); self.depth=0; self.main_buttons=[]
        def handle_starttag(self,tag,attrs):
            if tag=='details': self.depth+=1
            if tag=='button' and self.depth==0: self.main_buttons.append(dict(attrs).get('id'))
            if tag=='select' and self.depth==0: assert dict(attrs).get('id')=='scenario'
        def handle_endtag(self,tag):
            if tag=='details': self.depth-=1
    client=TestClient(create_app(saved=tmp_path,runtime=tmp_path))
    parsed=Controls(); parsed.feed(client.get('/story').text)
    assert parsed.main_buttons==['run-live','play','next']


def test_evidence_is_separate_and_preserves_all_tables(tmp_path):
    client=TestClient(create_app(saved=tmp_path,runtime=tmp_path))
    page=client.get('/story/evidence')
    assert page.status_code==200
    assert 'Evidence register' in page.text and 'coverage-results' in page.text
    for name in ('timing-results','real-results','check-results','case-results','story-results'):
        assert f'id="{name}"' in page.text
    assert 'Saare tests' not in page.text and 'Kya bana' not in page.text


def test_individual_cases_keep_failures_and_missing_evidence(tmp_path):
    from dashboard.story import individual_checks
    folder=tmp_path/'evidence'; folder.mkdir()
    (folder/'isolation.txt').write_text('Direct blue-defense blocked FAIL\n',encoding='utf-8')
    (folder/'audit-docker.txt').write_text('unmodified VALID\nedit one event INVALID\n',encoding='utf-8')
    rows=individual_checks(tmp_path)
    assert len(rows)==19
    assert rows[0]['status']=='FAIL'
    assert next(r for r in rows if r['test']=='edit one event')['status']=='PASS'
    assert next(r for r in rows if r['test']=='delete last 3 events')['status']=='NOT RUN'


def test_real_summary_projects_only_numbers_and_provider(tmp_path):
    from dashboard.story import real_model_summary
    saved=tmp_path/'prototype'; saved.mkdir()
    secret='sk-private BLUE_SECRET_CANARY_7391 pineapple'
    write(tmp_path/'real_results.json',dict(provider='DeepSeek',sample_size=150,api_key=secret,
        metrics=dict(p50_seconds=1.18,p95_seconds=secret),requests=[dict(prompt=secret)]))
    write(tmp_path/'leak_counts.json',dict(attempts=20,raw_rule_leaks=2,score_verdict_gateway_rule_leaks=0,
        attempt_results=[dict(raw_output=secret)]))
    value=real_model_summary(saved)
    assert value['provider']=='DeepSeek' and value['leaks']['raw_rule_leaks']==2
    assert value['metrics']['p95_seconds'] is None
    for word in secret.split(): assert word not in json.dumps(value)


def test_comparison_projection_cannot_serve_arbitrary_outputs_or_reasons(tmp_path):
    from dashboard.story import comparison_projection
    secret='sk-private BLUE_SECRET_CANARY_7391'
    write(tmp_path/'comparison.json',dict(status='complete',arms=[dict(policy='raw',requests=[dict(
        case='allowed',prompt=secret,trace=dict(reason=secret,model_answer=secret,blue_allowed=True))])]))
    value=comparison_projection(tmp_path)
    row=value['arms'][0]['requests'][0]
    assert row['trace']['model_answer'] is None and row['trace']['reason']=='not_recorded'
    assert row['trace']['blue_allowed'] is True
    for word in secret.split(): assert word not in json.dumps(value)


def test_backend_evidence_projects_only_counts_and_status(tmp_path):
    from dashboard.story import evidence_rows
    write(tmp_path/'evidence/backend-upgrade-verification.json',
          {'python':{'status':'PASS','passed':106,'api_key':'never-display-this-secret'},'javascript':{'status':'FAIL','passed':12}})
    rows=evidence_rows(tmp_path)
    assert rows[-2]['metric']=='106 passed' and rows[-2]['status']=='PASS'
    assert rows[-1]['status']=='FAIL'
    assert 'never-display-this-secret' not in json.dumps(rows)


def test_latest_full_suite_supersedes_old_absence_without_hiding_failures(tmp_path):
    from dashboard.story import evidence_rows
    write(tmp_path/'evidence/results.json',{'rows':[
        {'test':'Test suite (host, Windows)','result':'NOT RUN'},
        {'test':'Collector timing check (isolated host run)','result':'FAIL'}]})
    write(tmp_path/'evidence/backend-upgrade-verification.json',{'python':{'status':'PASS','passed':106}})
    rows=evidence_rows(tmp_path)
    assert [r['status'] for r in rows if r['test']=='Test suite (host, Windows)']==['PASS']
    assert rows[0]['metric']=='106 passed'
    assert any(r['status']=='FAIL' for r in rows)
