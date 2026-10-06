const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'docs/index.html'),'utf8');
const scripts=[...html.matchAll(/<script>([\s\S]*?)<\/script>/g)].map(m=>m[1]);
function page(theme=null){
  const nodes=new Map(),store=new Map(theme?[['da-theme',theme]]:[]),events={};
  function node(id){if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:'',parentElement:{},events:{},querySelectorAll:()=>[],addEventListener(name,fn){this.events[name]=fn},appendChild:()=>{},scrollIntoView(){this.scrolled=true}});return nodes.get(id)}
  const data=JSON.parse(fs.readFileSync(path.join(root,'docs/data/patches.json'),'utf8'));
  const document={documentElement:{dataset:{}},getElementById:node,querySelectorAll:()=>[],createElement:()=>({setAttribute:()=>{},addEventListener:()=>{}})};
  const context={URL,console,performance:{getEntriesByType:()=>[{type:'navigate'}]},sessionStorage:{},localStorage:{getItem:k=>store.get(k)||null,setItem:(k,v)=>store.set(k,v),removeItem:k=>store.delete(k)},document,location:{hash:''},window:{addEventListener:(k,v)=>events[k]=v},fetch:()=>new Promise(()=>{}),PatchDownloads:{refresh:async()=>[],refreshActivity:async()=>[]},data};
  vm.createContext(context);for(const script of scripts)vm.runInContext(script,context);vm.runInContext('applyData(data)',context);
  return {context,node,data,store,events};
}
test('archive renders catalogue, compact current asset links, report and share links',()=>{
  const {node,data}=page();const out=node('list').innerHTML;
  assert.equal((out.match(/class="row"/g)||[]).length,data.patches.length);
  for(const p of data.patches.filter(p=>p.latest_release))assert(out.includes(p.url+'/releases/latest'));
  assert(out.includes('영상 자막 ✓'));assert(!out.includes('동영상 자막 ✓'));
  assert(out.includes('href="#eve-zero"'));assert(out.includes('id="eve-zero"'));
  assert(out.includes('aria-label="EVE_ZERO_Korean_Patch_v1.1.zip'));
  assert(!out.includes('>EVE_ZERO_Korean_Patch_v1.1.zip</a>'));
  assert.equal((out.match(/>오류 제보<\/a>/g)||[]).length,data.patches.length);
  assert.equal((out.match(/>작품 소개<\/a>/g)||[]).length,3);
});
test('file tooltips retain full names, old release files stay hidden and URL injection is rejected',()=>{
  const {context}=page();const out=vm.runInContext('releaseAssetsMarkup({latest_release:{tag:"v1.1"},assets:[{tag:"v1.0",name:"OLD.zip",url:"https://example.com/old",downloads:99},{tag:"v1.1",name:"LONG<&.zip",url:"https://example.com/new",downloads:2}]})',context);
  assert(!out.includes('OLD.zip'));assert(out.includes('title="LONG&lt;&amp;.zip"'));assert(out.includes('>v1.1 · 2회</a>'));
  assert(!vm.runInContext('releaseAssetsMarkup({latest_release:{tag:"v1.1"},assets:[{tag:"v1.1",name:"evil.zip",url:"javascript:alert(1)",downloads:2}]})',context).includes('javascript:'));
  assert.equal(vm.runInContext('gameId({repo:"x\\\" onclick=bad-kr-patch"})',context).includes('"'),false);
});
test('fresh badges use release dates, reject future dates and expire after seven days',()=>{
  const {context}=page();context.now=Date.parse('2026-10-10T12:00:00Z');
  context.p={latest_release:{tag:'v1.1',published_at:'2026-10-05T12:00:00Z'},assets:[],changelog:[{v:'1.1'},{v:'1.0'}]};
  assert(vm.runInContext('freshBadge(p,now)',context).includes('UPDATE'));
  context.p.changelog=[{v:'1.1'}];assert(vm.runInContext('freshBadge(p,now)',context).includes('NEW'));
  context.p.latest_release.published_at='2026-10-11T12:00:00Z';assert.equal(vm.runInContext('freshBadge(p,now)',context),'');
  context.p.latest_release.published_at='2026-10-03T12:00:00Z';assert.equal(vm.runInContext('freshBadge(p,now)',context),'');
});
test('updates are latest five released records and exclude tag guesses, missing dates and unreleased work',()=>{
  const {context}=page();context.records=Array.from({length:7},(_,i)=>({repo:'game'+i,title:'Game'+i,latest_release:{tag:'v1'},changelog:[{v:'1',date:'2020-01-'+String(i+1).padStart(2,'0'),added:['video']}]}));
  context.records.push({repo:'unreleased',changelog:[{v:'9',date:'2026-01-01',added:['video']}],title:'UNRELEASED'},{repo:'guess',latest_release:{},changelog:[{v:'9',date:'2026-01-01',date_source:'tag',added:['video']}],title:'TAG-GUESS'});
  const out=vm.runInContext('updatesMarkup(records)',context);
  assert.equal((out.match(/class="update-item"/g)||[]).length,5);
  assert(out.indexOf('Game6')<out.indexOf('Game5'));assert(!out.includes('UNRELEASED'));assert(!out.includes('TAG-GUESS'));
});
test('theme selection is remembered and system option clears override',()=>{
  const {context,node,store}=page('dark');assert.equal(context.document.documentElement.dataset.theme,'dark');assert.equal(node('theme').value,'dark');
  node('theme').value='light';node('theme').events.change();assert.equal(store.get('da-theme'),'light');
  node('theme').value='auto';node('theme').events.change();assert.equal(context.document.documentElement.dataset.theme,undefined);assert.equal(store.has('da-theme'),false);
});
test('game address restores target even when saved filters hide it',()=>{
  const {context,node}=page();context.location.hash='#eve-zero';
  vm.runInContext('state.plat="PS3";state.series="동방"',context);node('q').value='hidden';
  vm.runInContext('revealGame()',context);
  assert.equal(vm.runInContext('state.plat',context),'전체');assert.equal(node('q').value,'');assert.equal(node('eve-zero').scrolled,true);
});
test('report URL prefills a draft without sending it, and more counts remain separate',()=>{
  const {context}=page();const url=new URL(vm.runInContext('issueUrl(data.patches[0])',context));
  assert.equal(url.origin,'https://github.com');assert(url.pathname.endsWith('/issues/new'));
  assert(url.searchParams.get('body').includes('게임 판본'));assert(url.searchParams.get('body').includes('스크린샷'));
  const out=vm.runInContext('historyMarkup({changelog:[{v:"1.1",added:["video"],fixed:["오류"]}]})',context);
  assert(out.includes('class="small history-more">외 1건'));
});
