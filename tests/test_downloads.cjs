const test=require('node:test');
const assert=require('node:assert/strict');
const live=require('../docs/downloads.js');

const asset=(downloads=10,asset_id=1)=>({name:'patch.zip',tag:'v1.0',asset_id,downloads});
const release=(tag='v1.0',count=10,id=1)=>({tag_name:tag,draft:false,assets:[{name:'patch.zip',id,download_count:count}]});
const response=(releases,link='')=>({ok:true,json:async()=>releases,headers:{get:()=>link}});
const storage=()=>{const data=new Map();return {getItem:k=>data.get(k)||null,setItem:(k,v)=>data.set(k,v)}};
const patch=(repo='game')=>({repo,downloads:10,assets:[asset()],download_ledger:{[`${repo}/v1.0/patch.zip`]:{asset_id:1,last_count:10,carried:0,removed:false}}});

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
