const test=require('node:test');
const assert=require('node:assert/strict');
const live=require('../docs/downloads.js');

const asset=(downloads=10,asset_id=1)=>({name:'patch.zip',tag:'v1.0',asset_id,downloads});
const release=(tag='v1.0',count=10,id=1)=>({tag_name:tag,draft:false,assets:[{name:'patch.zip',id,download_count:count}]});
const response=(releases,link='')=>({ok:true,json:async()=>releases,headers:{get:()=>link}});
const storage=()=>{const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)}};
const patch=(repo='game')=>({repo,downloads:10,assets:[asset()],download_ledger:{[`${repo}/v1.0/patch.zip`]:{asset_id:1,last_count:10,carried:0,removed:false}}});

test('README pushes refresh recent activity immediately on reload, including same-day changes',async()=>{
  const p={...patch(),activity_at:'2026-10-05T01:00:00Z',latest_release:{published_at:'2026-10-04T00:00:00Z'}};
  const cache=storage();let calls=0;const modes=[];
  const fetcher=async(url,options)=>{calls++;modes.push(options.cache);return response([{name:'game',pushed_at:calls===1?'2026-10-05T02:00:00Z':'2026-10-05T03:00:00Z'}])};
  await live.refreshActivity([p],{fetcher,storage:cache,now:1000});
  assert.equal(p.activity_at,'2026-10-05T02:00:00Z');
  await live.refreshActivity([p],{fetcher,storage:cache,now:2000});assert.equal(calls,1);
  await live.refreshActivity([p],{fetcher,storage:cache,now:3000,force:true});
  assert.equal(p.activity_at,'2026-10-05T03:00:00Z');assert.equal(modes[1],'no-store');
});

test('activity excludes recorded maintenance and preserves newer releases and failure fallback',async()=>{
  const p={...patch(),activity_at:'2026-10-01T00:00:00Z',activity_exclusion:{ignored_pushed_at:'2026-10-05T00:00:00Z',previous_activity_at:'2026-10-01T00:00:00Z'}};
  await live.refreshActivity([p],{fetcher:async()=>response([{name:'game',pushed_at:'2026-10-05T00:00:00Z'}])});
  assert.equal(p.activity_at,'2026-10-01T00:00:00Z');
  p.latest_release={published_at:'2026-10-06T00:00:00Z'};
  await live.refreshActivity([p],{fetcher:async()=>response([{name:'game',pushed_at:'2026-10-05T01:00:00Z'}])});
  assert.equal(p.activity_at,p.latest_release.published_at);
  const old=JSON.stringify(p);
  assert.deepEqual(await live.refreshActivity([p],{fetcher:async()=>({ok:false})}),[]);assert.equal(JSON.stringify(p),old);
});

test('new release refresh updates version, activity, files, history and video together',async()=>{
  const p={...patch(),status:'released',activity_at:'2026-10-04T00:00:00Z',scope:{video:{state:'none',since:null}},changelog:[{v:'1.0',added:['title']}]};
  const r={...release('v1.1',3,2),name:'patch v1.1',html_url:'https://github.com/Dollars-Archive/game/releases/tag/v1.1',published_at:'2026-10-05T04:17:00Z',body:'## v1.1 패치 내용\n- 오프닝 & 게임 내 영상 & 엔딩 자막 추가\n## v1.0 주요 반영 내용\n- 이미지 번역 추가'};
  r.assets[0].browser_download_url='https://github.com/Dollars-Archive/game/releases/download/v1.1/patch.zip';
  await live.refresh([p],{fetcher:async()=>response([r]),force:true});
  assert.equal(p.latest_release.tag,'v1.1');assert.equal(p.activity_at,r.published_at);
  assert.equal(p.assets[0].tag,'v1.1');assert.equal(p.downloads,13);
  assert.deepEqual(p.scope.video,{state:'done',since:'1.1'});assert.equal(p.scope.image,undefined);
  assert.equal(p.changelog[0].v,'1.1');
  await live.refresh([p],{fetcher:async()=>response([r]),force:true});
  assert.equal(p.changelog.length,2);assert.equal(p.scope.video.since,'1.1');
});

test('planned additions and unrelated old sections are not inferred',()=>{
  assert.deepEqual(live.releaseAdditions({tag_name:'v1.1',body:'## v1.1 패치 내용\n- 동영상 자막 추가 예정\n## v1.0 주요 반영 내용\n- 이미지 번역 추가'}),[]);
});

test('ledger preserves replaced, decreased, removed and returning assets',()=>{
  const p=patch();
  assert.equal(live.ledgerTotal('game',[asset(3,2)],p.download_ledger),13);
  assert.equal(live.ledgerTotal('game',[asset(2)],p.download_ledger),12);
  assert.equal(live.ledgerTotal('game',[],p.download_ledger),10);
  p.download_ledger['game/v1.0/patch.zip'].removed=true;
  assert.equal(live.ledgerTotal('game',[asset(12)],p.download_ledger),12);
});

test('ten minute session cache avoids repeated API requests and expires',async()=>{
  let requests=0;const cache=storage();
  const fetcher=async()=>{requests++;return response([release()])};
  await live.fetchAssets('game',{fetcher,storage:cache,now:1000});
  await live.fetchAssets('game',{fetcher,storage:cache,now:1000+live.TTL-1});
  assert.equal(requests,1);
  await live.fetchAssets('game',{fetcher,storage:cache,now:1000+live.TTL});
  assert.equal(requests,2);
});

test('a newer collected ledger invalidates older cached counts',async()=>{
  let requests=0;const cache=storage();
  const fetcher=async()=>{requests++;return response([release('v1.0',requests===1?10:11)])};
  await live.fetchAssets('game',{fetcher,storage:cache,now:1000});
  const result=await live.fetchAssets('game',{fetcher,storage:cache,now:2000,minAt:1500});
  assert.equal(requests,2);assert.equal(result.assets[0].downloads,11);
});

test('forced reload bypasses session and HTTP caches and stores fresh counts',async()=>{
  let requests=0;const cache=storage(),modes=[];
  const fetcher=async(url,options)=>{requests++;modes.push(options.cache);return response([release('v1.0',requests===1?10:12)])};
  await live.fetchAssets('game',{fetcher,storage:cache,now:1000});
  const p=patch();
  await live.refresh([p],{fetcher,storage:cache,now:2000,force:true});
  assert.equal(requests,2);assert.equal(p.downloads,12);assert.equal(modes[1],'no-store');
  assert.equal((await live.fetchAssets('game',{fetcher,storage:cache,now:3000})).assets[0].downloads,12);
  assert.equal(requests,2);
});

test('failed forced reload retains collected counts and the valid cache',async()=>{
  const cache=storage();
  await live.fetchAssets('game',{fetcher:async()=>response([release()]),storage:cache,now:1000});
  const p=patch(),old=JSON.stringify(p);
  const results=await live.refresh([p],{fetcher:async()=>({ok:false,status:403}),storage:cache,now:2000,force:true});
  assert.equal(results.length,0);assert.equal(JSON.stringify(p),old);
  const cached=await live.fetchAssets('game',{fetcher:async()=>{throw new Error('must use cache')},storage:cache,now:3000});
  assert.equal(cached.assets[0].downloads,10);
});

test('pagination includes prereleases and excludes draft and tool releases',async()=>{
  const calls=[];
  const fetcher=async url=>{calls.push(url);return calls.length===1?response([release(),release('trainer-v1.0',999),{...release('v2.0',999),draft:true}],'<https://api.github.com/repos/Dollars-Archive/game/releases?per_page=100&page=2>; rel="next"'):response([{...release('v2.0-beta',2,2),prerelease:true}])};
  const result=await live.fetchAssets('game',{fetcher});
  assert.equal(calls.length,2);assert.equal(result.assets.reduce((sum,a)=>sum+a.downloads,0),12);
});

test('API blocked or malformed keeps all collected values',async()=>{
  for(const fetcher of [async()=>({ok:false,status:403}),async()=>{throw new Error('blocked')},async()=>response([{tag_name:'v1.0',assets:[{name:'bad',id:1,download_count:-1}]}])]){
    const p=patch(),old=JSON.stringify(p);assert.deepEqual(await live.refresh([p],{fetcher}),[]);assert.equal(JSON.stringify(p),old);
  }
});

test('at most three API requests run together and partial failures are isolated',async()=>{
  let active=0,max=0;
  const fetcher=async url=>{active++;max=Math.max(max,active);await new Promise(r=>setTimeout(r,8));active--;return url.includes('/game4/')?{ok:false}:response([release('v1.0',11)])};
  const patches=Array.from({length:8},(_,i)=>patch(`game${i}`));
  const results=await live.refresh(patches,{fetcher});
  assert.equal(max,3);assert.equal(results.length,7);assert.equal(patches[4].downloads,10);assert.equal(patches[0].downloads,11);
});

test('blocked storage still refreshes and pagination cannot leave GitHub',async()=>{
  const inaccessible={getItem:()=>{throw new Error('blocked')},setItem:()=>{throw new Error('blocked')}};
  assert.equal((await live.fetchAssets('game',{storage:inaccessible,fetcher:async()=>response([release()])})).assets.length,1);
  let requests=0;
  await assert.rejects(live.fetchAssets('game',{fetcher:async()=>{requests++;return response([], '<https://other.example/releases>; rel="next"')}}));
  assert.equal(requests,1);
});


test('deleted final release clears collected release metadata without erasing history or totals',async()=>{
  const p={...patch(),status:'released',latest_release:{tag:'v1.0',published_at:'2026-10-06T00:00:00Z'},activity_at:'2026-10-06T01:00:00Z',changelog:[{v:'1.0',added:['title']}],scope:{title:{state:'done',since:'1.0'}}};
  const history=JSON.stringify(p.changelog),scope=JSON.stringify(p.scope);
  assert.equal((await live.refresh([p],{fetcher:async()=>response([]),force:true})).length,1);
  assert.equal(p.latest_release,null);assert.equal(p.status,'wip');assert.deepEqual(p.assets,[]);
  assert.equal(p.downloads,10);assert.equal(p.downloads_current,0);assert.equal(p.downloads_carried,10);
  assert.equal(p.activity_at,'2026-10-06T01:00:00Z');
  assert.equal(JSON.stringify(p.changelog),history);assert.equal(JSON.stringify(p.scope),scope);
});

test('prerelease-only results clear stable version and preserve paused status',async()=>{
  const p={...patch(),status:'paused',latest_release:{tag:'v1.0'}};
  await live.refresh([p],{fetcher:async()=>response([{...release('v2.0-beta',2,2),prerelease:true}])});
  assert.equal(p.latest_release,null);assert.equal(p.status,'paused');assert.equal(p.assets[0].tag,'v2.0-beta');
});

test('incomplete stable release metadata does not clear a collected release',async()=>{
  const p={...patch(),status:'released',latest_release:{tag:'v1.0'}};
  await live.refresh([p],{fetcher:async()=>response([release()])});
  assert.equal(p.latest_release.tag,'v1.0');assert.equal(p.status,'released');
});
