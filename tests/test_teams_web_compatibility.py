"""Teams DOM contracts in synthetic markup; no browser, account or company data."""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import unittest
import xml.etree.ElementTree as ET
from datetime import date, datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PRODUCT = Path(__file__).resolve().parents[1] / 'LoadMonitor25'
# A small DOM test double implements selectors against markup rather than
# matching production script text. Node executes the actual collector scripts.
DOM = r"""
const input = JSON.parse(require('fs').readFileSync(0,'utf8'));
function split(s, separator) {
  let parts=[], p='', depth=0, quote='';
  for(const c of s) {
    if(quote) { p+=c; if(c===quote)quote=''; continue; }
    if(c==='"'||c==="'") {quote=c;p+=c;continue;}
    if(c==='[')depth++; if(c===']')depth--;
    if(c===separator && !depth) {if(p.trim())parts.push(p.trim());p='';}else p+=c;
  }
  if(p.trim())parts.push(p.trim()); return parts;
}
function simple(e,s) {
  const tag=s.match(/^[\w*-]+/); if(tag && tag[0]!=='*' && tag[0]!==e.tag)return false;
  return [...s.matchAll(/\[([^\]=*^\s]+)(?:([*^]?=)["']?([^"'\]]*)["']?)?\]/g)].every(m=>{
    const val=e.getAttribute(m[1]); if(val===null)return false;
    return !m[2] || (m[2]==='=' ? val===m[3] : m[2]==='*=' ? val.includes(m[3]) : val.startsWith(m[3]));
  });
}
function match(e,s) {
  return split(s,',').some(group=>{
    const parts=split(group,' ');let cur=e;
    if(!simple(cur,parts.pop()))return false;
    while(parts.length) {const p=parts.pop();cur=cur.parentElement;while(cur && !simple(cur,p))cur=cur.parentElement;if(!cur)return false;}
    return true;
  });
}
class Element {
  constructor(data,parent=null){this.tag=data.tag;this.attrs=data.attrs||{};this.raw=data.text||'';this.parentElement=parent;this.children=(data.children||[]).map(x=>new Element(x,this));}
  get textContent(){return this.raw+this.children.map(x=>x.textContent).join('');}
  get childElementCount(){return this.children.length;}
  get href(){return this.attrs.href||'';}
  get pathname(){return this.href?new URL(this.href).pathname:'';}
  get value(){return this.attrs.value||'';}
  getAttribute(k){return Object.hasOwn(this.attrs,k)?this.attrs[k]:null;}
  getClientRects(){return [{}];}
  matches(s){return match(this,s);}
  closest(s){for(let e=this;e;e=e.parentElement)if(e.matches(s))return e;return null;}
  contains(e){for(let p=e;p;p=p.parentElement)if(p===this)return true;return false;}
  querySelectorAll(s){const found=[];for(const c of this.children){if(c.matches(s))found.push(c);found.push(...c.querySelectorAll(s));}return found;}
  querySelector(s){return this.querySelectorAll(s)[0]||null;}
  scrollIntoView(){}
  dispatchEvent(e){events.push({id:this.attrs.id||'',type:e.type});}
  click(){this.dispatchEvent({type:'click'});}
}
const document = new Element(input.dom), window={}, location={href:'https://teams.microsoft.com/v2/'};
const events=[];const MouseEvent=class{constructor(type){this.type=type;}};
const results=input.scripts.map(s=>{const value=eval(s);try{return JSON.parse(value);}catch{return value;}});
process.stdout.write(JSON.stringify({results,events}));
"""


class TeamsWebCompatibilityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix='lm25-teams-web-markup-')
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for folder in ('collect', 'core', 'config'):
            (self.root / folder).mkdir()
        for name in ('Get-TeamsWeb.py', 'Get-OutlookWeb.py'):
            shutil.copyfile(PRODUCT / 'collect' / name, self.root / 'collect' / name)
        shutil.copyfile(PRODUCT / 'core/collection_state.py', self.root / 'core/collection_state.py')
        spec = importlib.util.spec_from_file_location('teams_markup_fixture', self.root / 'collect/Get-TeamsWeb.py')
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def dom(self, markup, *scripts):
        def data(element):
            return {'tag': element.tag, 'attrs': element.attrib, 'text': element.text or '',
                    'children': [data(child) for child in element]}
        node = shutil.which('node')
        self.assertTrue(node, 'Node is required by the project verification runtime')
        result = subprocess.run([node, '-e', DOM], input=json.dumps({'dom': data(ET.fromstring(markup)), 'scripts': scripts}),
                                capture_output=True, text=True, encoding='utf-8', timeout=10, check=False)
        self.assertEqual(result.returncode, 0, result.stderr)
        return json.loads(result.stdout)

    def read(self, pages, on_undated=None):
        return self.mod.read_chat(None, 0, 'Room', date(2026, 6, 1), date(2026, 6, 30), date(2026, 9, 30),
                                  fake={'0': pages}, conversation_id='room-id', on_undated=on_undated)[0]

    def test_legacy_and_modern_markup_yield_same_message_once(self):
        for outer, body, stamp in [('data-tid="chat-pane-item"', 'messageBodyContent', 'message-timestamp'),
                                   ('role="article" data-message-id="m1"', 'message-body', 'timestamp')]:
            markup = f'''<html><main role="main"><h1>Room</h1><section role="log" data-chat-id="room-id">
              <div {outer}><div data-tid="chat-pane-message" data-message-id="m1">
              <span data-tid="message-author-name">Person</span><time data-tid="{stamp}" datetime="2026-06-03T09:00:00+09:00"/>
              <div data-tid="{body}">Original evidence</div></div></div></section></main></html>'''
            result = self.dom(markup, self.mod.JS_MSGS, self.mod.JS_PANE)['results']
            self.assertEqual(result[0]['n'], 1)
            self.assertEqual(result[0]['items'][0]['body'], 'Original evidence')
            self.assertEqual(result[0]['items'][0]['id'], 'm1')
            self.assertEqual(result[1]['conversation_id'], 'room-id')
            self.assertEqual(len(self.read([result[0]])), 1)

    def test_chat_list_union_finds_modern_and_legacy_without_menu_click(self):
        markup = '''<html><aside><div data-tid="chat-list"><div id="legacy" data-tid="chat-list-item" data-chat-id="old">
          <button id="menu">More options</button><span data-tid="chat-list-item-title">Old</span></div></div>
          <div role="tree"><div id="modern" role="treeitem" data-chat-id="new"><span data-tid="chat-title">New</span></div>
          <div role="treeitem"><span>Unrelated channel group</span></div></div></aside></html>'''
        result = self.dom(markup, self.mod.JS_CHATS, self.mod.JS_OPEN % json.dumps('old'))
        self.assertEqual({row['conversation_id'] for row in result['results'][0]['items']}, {'old', 'new'})
        self.assertEqual(result['results'][1], 'ok')
        self.assertEqual({event['id'] for event in result['events']}, {'legacy'})

    def test_hidden_chat_and_unrelated_main_list_are_not_messages(self):
        markup = '''<html><div hidden="hidden"><div data-tid="chat-list-item" data-chat-id="hidden"/></div>
          <main role="main"><h1>Files</h1><div role="listitem"><time datetime="2026-06-03T09:00:00Z"/><span>Attachment</span></div></main></html>'''
        result = self.dom(markup, self.mod.JS_CHATS, self.mod.JS_MSGS, self.mod.JS_READY)['results']
        self.assertEqual(result[0]['n'], 0)
        self.assertEqual(result[1]['n'], 0)
        self.assertEqual(result[2]['chats'], 0)
        self.assertEqual(result[2]['messages'], 0)

    def test_timestamp_titles_exclude_body_tooltips_and_sidebar_header(self):
        markup = '''<html><aside><span data-tid="chat-title">Wrong room</span></aside><main role="main"><h1>Room</h1>
          <div role="log"><div role="listitem" data-message-id="m1"><span data-tid="timestamp" title="2026-06-03 09:00">09:00</span>
          <div data-tid="message-body"><a title="2025-01-01 03:00">A referenced deadline</a></div></div></div></main></html>'''
        page = self.dom(markup, self.mod.JS_MSGS)['results'][0]
        self.assertEqual(page['chat'], 'Room')
        self.assertEqual(page['items'][0]['titles'], ['2026-06-03 09:00'])
        self.assertEqual(self.read([page])[0]['time'], '2026-06-03 09:00')

    def test_same_page_full_date_supports_short_replies_but_next_page_resets(self):
        pages = [{'items': [{'t': 'msg', 'id': 'a', 'ts': '2026-06-03 09:00', 'body': 'First'},
                            {'t': 'msg', 'id': 'b', 'ts': '09:01', 'body': '네'},
                            {'t': 'msg', 'id': 'c', 'ts': '09:02', 'body': 'OK'}]},
                 {'items': [{'t': 'msg', 'id': 'd', 'ts': '08:55', 'body': 'Date absent after scrolling'}]}]
        pending = []
        rows = self.read(pages, pending.extend)
        self.assertEqual([row['context_excerpt'] for row in rows], ['First', '네', 'OK'])
        self.assertEqual([row['time'] for row in rows], ['2026-06-03 09:00', '2026-06-03 09:01', '2026-06-03 09:02'])
        self.assertEqual(len(pending), 1)
        self.assertEqual(pending[0]['time'], '')
        self.assertEqual(pending[0]['time_precision'], 'unknown')

    def test_unknown_separator_and_missing_year_do_not_reuse_requested_year(self):
        pending = []
        rows = self.read([{'items': [{'t': 'msg', 'ts': '2026-06-03 09:00', 'body': 'Known'},
                                    {'t': 'sep', 'text': 'June 4'},
                                    {'t': 'msg', 'ts': '09:30', 'body': 'Request year cannot establish sent year'}]}], pending.extend)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(pending), 1)
        self.assertIsNone(self.mod.stamp(['June 3 09:00'], [], None, date(2020, 6, 1), date(2020, 6, 30), date(2026, 9, 30))[0])

    def test_surrounded_iso_preserves_offset_and_body_deadline_is_not_clock(self):
        value = '2026-06-30T23:45:00-07:00'
        expected = datetime.fromisoformat(value).astimezone().replace(tzinfo=None, second=0, microsecond=0)
        self.assertEqual(self.mod.iso_dt('Sent at '+value+' (edited)'), expected)
        self.assertIsNone(self.mod.stamp([], ['Please finish at 09:00'], date(2026, 6, 3), date(2026, 6, 1), date(2026, 6, 30), date(2026, 9, 30))[0])

    def test_undated_page_is_durable_before_interrupt_and_resolution_removes_pending(self):
        pages = [{'items': [{'t': 'msg', 'id': 'm', 'ts': '09:00', 'body': 'Pending original'}]}]
        with self.assertRaisesRegex(RuntimeError, 'stop'):
            def preserve(rows):
                self.mod.save_undated(rows)
                raise RuntimeError('stop')
            self.read(pages, preserve)
        path = self.root / 'data/collection_pending/teams_web_undated.csv'
        saved = self.mod.read_csv(path)
        self.assertEqual(saved[0]['context_excerpt'], 'Pending original')
        self.assertEqual(saved[0]['time'], '')
        self.assertFalse((self.root / 'data/m365/teams_web.csv').exists())
        pages[0]['items'][0]['ts'] = '2026-06-03 09:00'
        dated = self.read(pages)
        self.mod.save(dated, False)
        self.assertEqual(self.mod.read_csv(path), [])
        self.assertEqual(len(self.mod.read_csv(self.root / 'data/m365/teams_web.csv')), 1)

    def test_two_empty_date_queries_yield_budget_to_chat_list(self):
        fake = {'search': {f'2026-06-{day:02}': {'pages': [{'state': 'empty'}]} for day in range(1, 11)}}
        with patch.object(self.mod, 'log'):
            result = self.mod.collect_search(None, fake, str(self.root), date(2026, 6, 1), date(2026, 6, 10),
                                             date(2026, 9, 30), time.monotonic()+10, 4000, lambda _: None)
        self.assertEqual(result['attempted_this_run'], 2)
        self.assertIn('search_empty_yield_to_chat_list', result['reasons'])
        self.assertEqual(result['status'], 'partial')

    def test_resolving_reused_dom_id_does_not_remove_another_rooms_pending_body(self):
        pending = {'time': '', 'from': 'Person', 'chat': 'Room A', 'conversation_id': '',
                   'source_id': 'teams-dom:/local-row-1', 'source_kind': 'teams_web',
                   'context_excerpt': 'Original A', 'time_precision': 'unknown'}
        other = dict(pending, chat='Room B', context_excerpt='Original B')
        self.mod.save_undated([pending, other])
        self.mod.save([dict(pending, time='2026-06-03 09:00', time_precision='minute')], False)
        path = self.root / 'data/collection_pending/teams_web_undated.csv'
        self.assertEqual([(row['chat'], row['context_excerpt']) for row in self.mod.read_csv(path)], [('Room B', 'Original B')])
        self.mod.save_undated([other])
        self.assertEqual(len(self.mod.read_csv(path)), 1)

    def test_readiness_waits_for_real_chat_dom_instead_of_empty_main(self):
        browser = self.mod.Browser.__new__(self.mod.Browser)
        browser.deadline = None
        browser.href = lambda **kwargs: self.mod.TEAMS_URL
        states = iter([{'chats': 0, 'messages': 0}, {'chats': 1}, {'chats': 1}])
        calls = []
        def state(*args, **kwargs):
            calls.append(1)
            return next(states)
        browser.eval_json = state
        with patch.object(self.mod.time, 'sleep'):
            self.assertEqual(browser.wait_ready(), 'ok')
        self.assertEqual(len(calls), 3)

    def test_semantic_chat_name_without_server_id_is_ready(self):
        markup = '<html><div role="tree"><div role="treeitem"><span data-tid="chat-title">Room</span></div></div></html>'
        page = self.dom(markup, self.mod.JS_READY, self.mod.JS_CHATS)['results']
        self.assertGreater(page[0]['chats'], 0)
        self.assertEqual(page[1]['items'][0]['name'], 'Room')

    def test_all_direct_cdp_calls_and_reconnect_share_remaining_budget(self):
        now, calls = [0.0], []
        def invoke(*args, **kwargs):
            calls.append(kwargs['timeout'])
            now[0] += kwargs['timeout']
            return 'ok'
        driver = SimpleNamespace(call=invoke, eval=invoke, reconnect=invoke)
        with patch.object(self.mod.time, 'monotonic', side_effect=lambda: now[0]):
            cdp = self.mod.DeadlineCDP(driver, lambda: 1.25)
            self.assertEqual(cdp.call('Page.navigate', {'url': self.mod.TEAMS_URL}), 'ok')
            with self.assertRaises(TimeoutError):
                cdp.eval('location.href')
            with self.assertRaises(TimeoutError):
                cdp.reconnect()
        self.assertEqual(calls, [1.25])
        now[0] = 0
        with patch.object(self.mod.time, 'monotonic', side_effect=lambda: now[0]):
            cdp = self.mod.DeadlineCDP(driver, lambda: 0.5)
            cdp.reconnect()
        self.assertEqual(calls, [1.25, 0.5])

    def test_virtualized_same_count_different_messages_is_immediate_progress(self):
        browser = SimpleNamespace(eval_json=lambda *args, **kwargs: {'chat': 'Room', 'n': 20, 'fingerprint': 'old-1|old-20'})
        with patch.object(self.mod.time, 'sleep') as sleep:
            result = self.mod.wait_pane(browser, ('Room', 20, 'new-1|new-20'), 2)
        self.assertEqual(result, ('Room', 20, 'old-1|old-20'))
        self.assertEqual(sleep.call_count, 1)

    def test_switch_waits_for_message_loading_and_rejects_same_name_wrong_id(self):
        pages = iter([{'conversation_id': 'room-id', 'n': 0, 'busy': True},
                      {'conversation_id': 'wrong', 'chat': 'Room', 'n': 4},
                      {'conversation_id': 'room-id', 'chat': 'Room', 'n': 1}])
        browser = SimpleNamespace(eval_json=lambda _: next(pages))
        with patch.object(self.mod.time, 'sleep'):
            self.assertTrue(self.mod.wait_chat(browser, {'conversation_id': 'room-id'}, 'Room'))

    def test_legacy_semantic_list_and_plain_timestamp_survive_complete_main_flow(self):
        markup = '''<html><aside><div role="tree"><div role="treeitem" title="Room" id="room-row">
          <button role="button" aria-label="Room" id="room-button"><span>Room</span></button></div></div></aside>
          <main role="main"><h1>Room</h1><div role="listitem" data-item-id="m1">
          <span data-tid="message-author-name">Person</span><span title="2026-06-03 09:00">09:00</span>
          <div data-tid="messageBodyContent">Original prior-version message</div></div></main></html>'''
        scripts = [self.mod.JS_READY, self.mod.JS_CHATS, self.mod.JS_PANE, self.mod.JS_MSGS,
                   self.mod.JS_OPEN % json.dumps('Room')]
        captured = self.dom(markup, *scripts)
        values = dict(zip(scripts, captured['results'], strict=True))
        browser = self.mod.Browser.__new__(self.mod.Browser)
        browser.deadline, browser.cfg = None, {}
        browser.start = lambda: True
        browser.close = lambda: None
        browser.href = lambda **kwargs: self.mod.TEAMS_URL
        browser.eval_json = lambda script, **kwargs: values.get(script, {})
        browser.cdp = SimpleNamespace(eval=lambda script: values.get(script, 'unsupported'), call=lambda *args: None)
        now = [0.0]
        with patch.object(self.mod, 'Browser', return_value=browser), \
                patch.object(self.mod.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(self.mod.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0]+seconds)), \
                patch.dict(os.environ, {'LM_NO_BROWSER': '', 'LM_TEAMSWEB_FAKE': ''}), \
                patch.object(sys, 'argv', ['collector', '--from', '2026-06-01', '--to', '2026-06-30', '--budget', '60']), \
                patch.object(self.mod, 'log'):
            self.assertEqual(self.mod.main(), 0)
        stored = self.mod.read_csv(self.root / 'data/m365/teams_web.csv')
        self.assertEqual([(row['time'], row['context_excerpt']) for row in stored],
                         [('2026-06-03 09:00', 'Original prior-version message')])
        self.assertIn({'id': 'room-button', 'type': 'click'}, captured['events'])
        self.assertNotIn({'id': 'room-row', 'type': 'click'}, captured['events'])

    def test_transient_sso_redirect_continues_the_same_wait(self):
        browser = self.mod.Browser.__new__(self.mod.Browser)
        browser.deadline = None
        locations = iter(['https://login.microsoftonline.com/tenant/oauth2/authorize',
                          self.mod.TEAMS_URL, self.mod.TEAMS_URL])
        browser.href = lambda **kwargs: next(locations)
        browser.eval_json = lambda *args, **kwargs: {'chats': 1}
        with patch.object(self.mod.time, 'sleep'), patch.object(self.mod, 'log'):
            self.assertEqual(browser.wait_ready(), 'ok')

    def test_grouped_sidebar_does_not_replace_all_chat_children_with_folder(self):
        markup = '''<html><div data-tid="chat-list" role="tree"><div role="treeitem" aria-expanded="true" title="Favorites">
          <div role="group"><div role="treeitem" data-chat-id="room-a" title="Room A"><span>Room A</span></div>
          <div role="treeitem" data-chat-id="room-b" title="Room B"><span>Room B</span></div></div>
          </div></div></html>'''
        page = self.dom(markup, self.mod.JS_CHATS)['results'][0]
        self.assertEqual([item['name'] for item in page['items']], ['Room A', 'Room B'])
        self.assertEqual({item['conversation_id'] for item in page['items']}, {'room-a', 'room-b'})

    def test_legacy_plain_leaves_keep_author_clock_and_body_without_tid(self):
        markup = '''<html><main role="main"><h1>Room</h1><div role="separator">2026-06-03</div>
          <div role="listitem"><span>Person</span><span>09:00</span><p>Plain original content</p></div>
          </main></html>'''
        page = self.dom(markup, self.mod.JS_MSGS)['results'][0]
        rows = self.read([page])
        self.assertEqual([(row['from'], row['time'], row['context_excerpt']) for row in rows],
                         [('Person', '2026-06-03 09:00', 'Plain original content')])

    def test_login_requiring_user_stops_at_deadline_and_keeps_distinct_status(self):
        browser = self.mod.Browser.__new__(self.mod.Browser)
        browser.deadline = 2.0
        browser.href = lambda **kwargs: 'https://login.microsoftonline.com/tenant/login'
        browser.eval_json = lambda *args, **kwargs: {'login': True}
        now = [0.0]
        with patch.object(self.mod.time, 'monotonic', side_effect=lambda: now[0]), \
                patch.object(self.mod.time, 'sleep', side_effect=lambda seconds: now.__setitem__(0, now[0]+seconds)), \
                patch.object(self.mod, 'log') as log:
            self.assertEqual(browser.wait_ready(), 'login')
        self.assertEqual(now[0], 2.0)
        self.assertEqual(log.call_count, 1)


if __name__ == '__main__':
    unittest.main()
