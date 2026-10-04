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
  assert.equal((node('list').innerHTML.match(/class="patch-summary"/g)||[]).length,data.patches.filter(p=>p.summary).length);
  assert(!node('list').innerHTML.includes('<span class="small">EVE</span>'));
  vm.runInContext('state.plat="Dreamcast";render()',context);
  assert.equal((node('list').innerHTML.match(/class="row"/g)||[]).length,data.patches.filter(p=>p.platforms.includes('Dreamcast')).length);
  vm.runInContext('state.plat="전체";state.series="동방";render()',context);
  assert.equal((node('list').innerHTML.match(/class="row"/g)||[]).length,data.patches.filter(p=>p.series==='동방').length);
  assert(node('footer').textContent.includes('수집값'));
});
test('card metadata stays compact and uniform',()=>{
  const {context,node}=page(async()=>[]);
  vm.runInContext('data.patches[0].genre="SHOULD-NOT-SHOW";data.patches[0].note="NOTE-SHOULD-NOT-SHOW";data.patches[0].release_jp="2001-03-22";data.patches[0].product_id="TEST-ID";data.patches[0].base_update="Ver.9.9";applyData(data)',context);
  const out=node('list').innerHTML;
  assert(out.includes('발매 2001.03.22'));
  assert(out.includes('ID <span class="mono">TEST-ID</span>'));
  assert(out.includes('기준 Ver.9.9'));
  assert(!out.includes('SHOULD-NOT-SHOW'));
  assert(!out.includes('NOTE-SHOULD-NOT-SHOW'));
});
test('summary text and source links cannot inject markup',()=>{
  const {context,node}=page(async()=>[]);
  vm.runInContext('data.patches[0].summary="<script>bad</script>\\n대사·메뉴 번역";data.patches[0].summary_source="javascript:alert(1)";applyData(data)',context);
  assert(node('list').innerHTML.includes('&lt;script&gt;bad&lt;/script&gt;'));
  assert(!node('list').innerHTML.includes('href="javascript:'));
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
