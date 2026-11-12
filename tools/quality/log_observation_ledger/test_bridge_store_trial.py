import copy
import json
import subprocess
import unittest
from pathlib import Path
from bridge_store_trial import commit_once, integrate
import log_ledger as ledger
from test_log_ledger import row, SERVICE, A, B, C, CANARY
ROOT=Path(__file__).parent


def bridged(rows, more=False, **extra):
    script="const {bridgePage}=require('./native_ledger_bridge');let s='';process.stdin.on('data',x=>s+=x);process.stdin.on('end',()=>{const x=JSON.parse(s);process.stdout.write(JSON.stringify(bridgePage(x.result,x.resource)));});"
    r=subprocess.run(['node','-e',script],cwd=ROOT,input=json.dumps({'resource':SERVICE,'result':{'isError':False,'structuredContent':dict(logs=rows,hasMore=more,**extra)}}),text=True,capture_output=True,check=True)
    if CANARY in r.stdout or SERVICE in r.stdout:
        raise AssertionError('unsafe bridge')
    return json.loads(r.stdout)


def fixture():
    first=bridged([row()],True,nextStartTime=B,nextEndTime=C)
    second=bridged([row()])
    alias=first['resource']
    def env(page,start):
        return {'query':{'resource':[alias],'type':['app'],'direction':'forward','startTime':start,'endTime':C,'limit':100},'reply':{'ok':True,'page':page}}
    return {'resource':alias,'window':{'startTime':A,'endTime':C},'direction':'forward','pages':[env(first['page'],A),env(second['page'],B)]}


def empty(transcript):
    return {'format':'q09-pseudonymous-bridge-trial-v1','revision':0,'ledger':ledger.new_state(transcript['resource'])}


class Store:
    def __init__(self,payload):self.payload=copy.deepcopy(payload);self.version=0;self.fault=None
    def read(self):return self.version,copy.deepcopy(self.payload)
    def replace(self,expected_version,payload):
        if self.fault=='conflict' or expected_version!=self.version:raise RuntimeError('CONFLICT')
        if self.fault=='before':raise RuntimeError('UNKNOWN')
        self.version+=1;self.payload=copy.deepcopy(payload)
        if self.fault=='after':raise RuntimeError('UNKNOWN')


class BridgeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):cls.transcript=fixture()
    def test_two_pages_duplicate_and_private_projection(self):
        out,report=integrate(empty(self.transcript),self.transcript)
        self.assertEqual(report['total_unique_log_ids'],1)
        self.assertEqual(report['scan']['chain_status'],'linked_terminal')
        self.assertIsNone(report['read_checkpoint'])
        self.assertNotIn(CANARY,json.dumps(out));self.assertNotIn(SERVICE,json.dumps(out))
    def test_repeated_run_no_duplicate_notification(self):
        s=Store(empty(self.transcript));commit_once(s,self.transcript);commit_once(s,self.transcript)
        self.assertEqual(s.payload['revision'],2)
        self.assertEqual(len(s.payload['ledger']['records']),1)
        self.assertEqual(len(ledger.pending_notifications(s.payload['ledger'],self.transcript['resource'])),1)
    def test_conflict_does_not_overwrite(self):
        s=Store(empty(self.transcript));s.fault='conflict'
        with self.assertRaisesRegex(RuntimeError,'CONFLICT'):commit_once(s,self.transcript)
        self.assertEqual(s.version,0)
    def test_ambiguous_before_or_after_never_retries(self):
        for fault,version in [('before',0),('after',1)]:
            s=Store(empty(self.transcript));s.fault=fault
            with self.assertRaisesRegex(RuntimeError,'UNKNOWN'):commit_once(s,self.transcript)
            self.assertEqual(s.version,version)
    def test_two_writers_same_version_only_one_commits(self):
        s=Store(empty(self.transcript));a,one=s.read();b,two=s.read()
        first,_=integrate(one,self.transcript);second,_=integrate(two,self.transcript)
        s.replace(expected_version=a,payload=first)
        with self.assertRaisesRegex(RuntimeError,'CONFLICT'):
            s.replace(expected_version=b,payload=second)
        self.assertEqual(s.version,1)
        self.assertEqual(s.payload,first)
    def test_missing_corrupt_state_rejected(self):
        for payload in [None,{},dict(format='wrong',revision=0,ledger=None),dict(format='q09-pseudonymous-bridge-trial-v1',revision=0,ledger=None)]:
            with self.assertRaises(ValueError):integrate(payload,self.transcript)
    def test_bad_cursor_private_text_not_forwarded(self):
        page=bridged([row()],True,nextStartTime=CANARY,nextEndTime=C)
        self.assertNotIn(CANARY,json.dumps(page));self.assertNotIn('nextStartTime',page['page'])
    def test_mixed_and_multiple_markers_remain_reviewable(self):
        for message in ['X_FAILED '*7000, 'WEB_PUSH_SEND_FAILED UNKNOWN_PRIVATE_FAILED '+CANARY,
                        'WEB_PUSH_SEND_FAILED DOCUMENT_IMPORT_FAILED '+CANARY]:
            page=bridged([row(message=message)])
            self.assertNotIn(CANARY,json.dumps(page))
            self.assertNotIn('UNKNOWN_PRIVATE_FAILED',json.dumps(page))
            t=copy.deepcopy(self.transcript);t['pages']=t['pages'][:1];t['pages'][0]['reply']['page']=page['page']
            out,report=integrate(empty(t),t)
            self.assertEqual(report['total_marker_or_review_records'],1)
            self.assertEqual(len(ledger.pending_notifications(out['ledger'],t['resource'])),1)
    def test_unknown_marker_preserved_for_review(self):
        page=bridged([row(message='NEW_FAILURE_FAILED '+CANARY)])
        self.assertEqual(page['page']['logs'][0]['message'],'Q09_UNCLASSIFIED_FAILED')
        t=copy.deepcopy(self.transcript);t['pages']=t['pages'][:1];t['pages'][0]['reply']['page']=page['page']
        out,report=integrate(empty(t),t)
        self.assertEqual(report['total_marker_or_review_records'],1)
        self.assertEqual(len(ledger.pending_notifications(out['ledger'],t['resource'])),1)


if __name__=='__main__':unittest.main()
