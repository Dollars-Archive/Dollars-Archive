const test=require('node:test'),assert=require('node:assert/strict');
const fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const root=path.resolve(__dirname,'..');
const html=fs.readFileSync(path.join(root,'docs/index.html'),'utf8');
const script=html.match(/<script>([\s\S]*?)<\/script>/)[1];
function page(refresh,navigationType="navigate"){
  const nodes=new Map();
  function node(id){if(!nodes.has(id))nodes.set(id,{value:'',innerHTML:'',textContent:'',parentElement:{},querySelectorAll:()=>[],addEventListener:()=>{},appendChild:()=>{}});return nodes.get(id)}
  const data=JSON.parse(fs.readFileSync(path.join(root,'docs/data/patches.json'),'utf8'));
  const context={URL,console,performance:{getEntriesByType:()=>[{type:navigationType}]},sessionStorage:{},localStorage:{getItem:()=>null},document:{getElementById:node,querySelectorAll:()=>[],createElement:()=>({setAttribute:()=>{},addEventListener:()=>{}})},fetch:()=>new Promise(()=>{}),PatchDownloads:{refresh},data};
  vm.createContext(context);vm.runInContext(script,context);vm.runInContext('applyData(data)',context);
  return {context,node,data};
}
test('collected page renders all covers and filters before API replies',()=>{
  const {context,node,data}=page(async()=>[]);
  assert.equal((node('list').innerHTML.match(/class="row"/g)||[]).length,data.patches.length);
  assert.equal((node('list').innerHTML.match(/loading="lazy"/g)||[]).length,data.patches.filter(p=>p.cover).length);
  assert.equal((node('list').innerHTML.match(/class="scope-chip /g)||[]).length,data.patches.length*6);
  assert.equal((node('list').innerHTML.match(/class="facts"/g)||[]).length,data.patches.length);
  assert(!node('list').innerHTML.includes('patch-summary'));
  assert(!node('list').innerHTML.includes('<span class="small">EVE</span>'));
  vm.runInContext('state.plat="Dreamcast";render()',context);
  assert.equal((node('list').innerHTML.match(/class="row"/g)||[]).length,data.patches.filter(p=>p.platforms.includes('Dreamcast')).length);
  vm.runInContext('state.plat="전체";state.series="동방";render()',context);
  assert.equal((node('list').innerHTML.match(/class="row"/g)||[]).length,data.patches.filter(p=>p.series==='동방').length);
  assert(node('footer').textContent.includes('수집값'));
});
test('release buttons resolve latest even before catalogue refresh',()=>{
  const {node,data}=page(async()=>[]);
  for(const p of data.patches.filter(p=>p.latest_release))assert(node('list').innerHTML.includes(`href="${p.url}/releases/latest"`));
});
test('asset links show only the newest stable release and preserve accumulated downloads',()=>{
  const {context}=page(async()=>[]);
  const out=vm.runInContext('releaseAssetsMarkup({latest_release:{tag:"v1.1"},downloads:300,assets:[{tag:"v1.0",name:"OLD.zip",url:"https://github.com/old",downloads:298},{tag:"v1.1",name:"NEW.zip",url:"https://github.com/new",downloads:2}]})',context);
  assert(out.includes('NEW.zip'));assert(!out.includes('OLD.zip'));
  const pending=vm.runInContext('releaseAssetsMarkup({latest_release:{tag:"v1.2"},assets:[{tag:"v1.1",name:"OLD.zip",url:"https://github.com/old",downloads:300}]})',context);
  assert(pending.includes('첨부파일 준비 중'));assert(!pending.includes('OLD.zip'));
});
test('guide chip is blank without a guide, direct for one guide and a game list for many',()=>{
  const {context}=page(async()=>[]);
  assert(vm.runInContext('walkthroughMarkup({repo:"game"})',context).includes('공략집 —'));
  const single=vm.runInContext('walkthroughMarkup({repo:"game",walkthroughs:[{url:"https://dollars-archive.github.io/Game-Walkthrough-Archive/guides/a.html"}]})',context);
  assert(single.includes('공략집 ✓'));assert(single.includes('/guides/a.html'));
  const many=vm.runInContext('walkthroughMarkup({repo:"game",walkthroughs:[{url:"https://example.com/a"},{url:"https://example.com/b"}]})',context);
  assert(many.includes('?game=game'));
});
test('new walkthrough catalogue updates the matching game chip on refresh',async()=>{
  const {context,node,data}=page(async()=>[]);
  const repo=data.patches[0].repo;
  context.fetch=async()=>({ok:true,json:async()=>({guides:[{patch_repo:repo,title:'공략',url:'https://dollars-archive.github.io/Game-Walkthrough-Archive/guides/a.html'}]})});
  await vm.runInContext('refreshWalkthroughs()',context);
  assert(node('list').innerHTML.includes('/guides/a.html'));
  assert.equal(data.patches[0].walkthroughs.length,1);
  assert.equal(data.patches[1].walkthroughs.length,0);
});
test('four facts and edition details keep empty values and full tooltips',()=>{
  const {context,node}=page(async()=>[]);
  vm.runInContext('data.patches[0].genre="RPG";data.patches[0].genre_full="전체 장르";data.patches[0].developer="개발사";data.patches[0].publisher="발매사";data.patches[0].playtime="";data.patches[0].note="NOTE-SHOULD-NOT-SHOW";data.patches[0].release_jp="2001-03-22";data.patches[0].product_id="TEST-ID";data.patches[0].base_update="Ver.9.9";applyData(data)',context);
  const out=node('list').innerHTML;
  assert(out.includes('<dt>발매</dt>'));
  assert(out.includes('2001.03.22'));
  assert(out.includes('<dd class="mono">TEST-ID</dd>'));
  assert(out.includes('<dd>Ver.9.9</dd>'));
  assert(out.includes('title="전체 장르">RPG'));
  assert(out.includes('title="개발 개발사 / 발매 발매사"'));
  assert(out.includes('<dt>플레이타임</dt><dd class="number" title="—">—</dd>'));
  assert(!out.includes('NOTE-SHOULD-NOT-SHOW'));
});
test('history, scope and facts cannot inject markup or unsafe release URLs',()=>{
  const {context,node}=page(async()=>[]);
  vm.runInContext('data.patches[0].changelog=[{v:"1.0",url:"javascript:alert(1)",added:["<script>bad</script>"]}];data.patches[0].developer="<img src=x>";data.patches[0].scope={video:{state:"done",since:"<script>"}};applyData(data)',context);
  assert(node('list').innerHTML.includes('&lt;script&gt;bad&lt;/script&gt;'));
  assert(!node('list').innerHTML.includes('href="javascript:'));
  assert(!node('list').innerHTML.includes('<img src=x>'));
});
test('one version has no history toggle, no versions shows pre-release',()=>{
  const {context,node}=page(async()=>[]);
  assert.equal(vm.runInContext('historyMarkup({changelog:[{v:"1.0",added:["ui"]}]})',context).includes('<details'),false);
  assert(vm.runInContext('historyMarkup({changelog:[]})',context).includes('배포 전'));
  assert(vm.runInContext('scopeMarkup({})',context).match(/scope-chip none/g).length===6);
});
test('multiple versions preview one category and expand all aligned rows',()=>{
  const {context}=page(async()=>[]);
  const out=vm.runInContext('historyMarkup({changelog:[{v:"1.1",date:"2026-10-05",added:["video"],fixed:["오류 A","오류 B"]},{v:"1.0",date:"2026-10-01",added:["ui"]}]})',context);
  assert(out.includes('변경 이력 (2)'));
  assert(out.includes('외 2건'));
  assert(out.includes('동영상 자막'));
  assert(out.includes('오류 A · 오류 B'));
  assert(out.includes('2026.10.05'));
});
test('scope chips show status without introduction versions',()=>{
  const {context}=page(async()=>[]);
  const out=vm.runInContext('scopeMarkup({scope:{title:{state:"done",since:null},video:{state:"done",since:"1.1"},image:{state:"partial",since:null}}})',context);
  assert(!out.includes('scope-since'));
  assert(!out.includes('1.1'));
  assert(out.includes('동영상 자막 ✓'));
  assert(out.includes('이미지 ✓'));
  assert(!out.includes('이미지 일부'));
});
test('README status tooltips distinguish unstarted, not applicable and unknown safely',()=>{
  const {context}=page(async()=>[]);
  const out=vm.runInContext('scopeMarkup({scope:{title:{state:"none",status:"미작업"},image:{state:"none",status:"해당 없음"},video:{state:"none",status:"확인 필요<script>"}}})',context);
  assert(out.includes('타이틀 — 미작업'));
  assert(out.includes('이미지 — 해당 없음'));
  assert(out.includes('확인 필요&lt;script&gt;'));
  assert(!out.includes('<script>'));
});
test('recent work uses activity date, not the order of bulk README pushes',()=>{
  const {context,node,data}=page(async()=>[]);
  data.patches=data.patches.slice(0,2);
  data.patches[0].activity_at='2026-10-04T00:00:00Z';data.patches[0].pushed_at='2026-10-05T00:00:00Z';
  data.patches[1].activity_at='2026-09-30T00:00:00Z';data.patches[1].pushed_at='2026-10-05T00:01:00Z';
  vm.runInContext('state.sort="최근 작업";applyData(data)',context);
  const out=node('list').innerHTML;
  assert(out.indexOf(`data-repo="${data.patches[0].repo}"`)<out.indexOf(`data-repo="${data.patches[1].repo}"`));
  assert(out.includes('최근 작업 2026.10.04'));
});
test('download rerender preserves an expanded history for the same game',()=>{
  const {context,node,data}=page(async()=>[]);
  const repo=data.patches[0].repo;
  const old={dataset:{section:'history'},closest:()=>({dataset:{repo}})};
  const restored={...old,open:false},other={dataset:{section:'edition'},closest:old.closest,open:false};
  node('list').querySelectorAll=selector=>selector==='.row details[open]'?[old]:selector==='.row details'?[restored,other]:[];
  vm.runInContext('render()',context);
  assert.equal(restored.open,true);
  assert.equal(other.open,false);
});
test('blocked API retains page, counts and collected footer',async()=>{
  const {context,node}=page(async()=>[]);
  const before={html:node('list').innerHTML,footer:node('footer').textContent,count:node('s-dl').textContent};
  await vm.runInContext('refreshDownloads()',context);
  assert.equal(node('list').innerHTML,before.html);assert.equal(node('footer').textContent,before.footer);assert.equal(node('s-dl').textContent,before.count);
});
test('live counts update footer and summary while using ledger freshness',async()=>{
  let options;
  const {context,node,data}=page(async(patches,opts)=>{options=opts;patches[0].downloads++;return patches.map(p=>({repo:p.repo,at:Date.now()}))});
  const old=data.summary.downloads;
  await vm.runInContext('refreshDownloads()',context);
  assert.equal(options.minAt,Date.parse(data.generated_at));
  assert.equal(options.force,false);
  assert.equal(node('s-dl').textContent,(old+1).toLocaleString('ko-KR'));
  assert(node('footer').textContent.includes('실시간'));
  assert(node('footer').textContent.includes('누적 집계 시작일'));
});
test('browser reload forces a fresh query and labels it correctly',async()=>{
  let options;
  const {context,node}=page(async(patches,opts)=>{options=opts;return patches.map(p=>({repo:p.repo,at:Date.now()}))},'reload');
  await vm.runInContext('refreshDownloads()',context);
  assert.equal(options.force,true);
  assert(node('footer').textContent.includes('새로 조회'));
});
test('partial refresh identifies mixed data instead of claiming all live',async()=>{
  const {context,node}=page(async patches=>[{repo:patches[0].repo,at:Date.now()}]);
  await vm.runInContext('refreshDownloads()',context);
  assert(node('footer').textContent.includes('일부 최신·일부 수집값'));
});
