/* Download-only refresh. Three workers, ten-minute per-session cache, no credentials. */
(function(root){
"use strict";
const TTL=10*60*1000;
function validAssets(assets){return Array.isArray(assets)&&assets.every(a=>typeof a.name==="string"&&typeof a.tag==="string"&&Number.isSafeInteger(a.asset_id)&&Number.isSafeInteger(a.downloads)&&a.downloads>=0)}
function ledgerTotal(repo,assets,previous={}){
  const records=Object.fromEntries(Object.entries(previous).map(([key,value])=>[key,{...value,removed:true}]));
  for(const asset of assets){
    const key=`${repo}/${asset.tag}/${asset.name}`,old=previous[key];
    let carried=old?.carried||0;
    if(old&&(old.asset_id!==asset.asset_id||asset.downloads<old.last_count))carried+=old.last_count;
    records[key]={asset_id:asset.asset_id,last_count:asset.downloads,carried,removed:false};
  }
  return Object.values(records).reduce((total,a)=>total+a.carried+a.last_count,0);
}
async function fetchAssets(repo,{fetcher=root.fetch,storage=null,now=Date.now(),minAt=0,force=false}={}){
  if(!/^[A-Za-z0-9_.-]+$/.test(repo))throw new Error("Invalid repository");
  const key=`da-downloads:v1:${repo}`;
  try{const cache=JSON.parse(storage?.getItem(key)||"null");if(!force&&cache&&cache.at>=minAt&&now-cache.at>=0&&now-cache.at<TTL&&validAssets(cache.assets))return cache}catch(e){}
  const assets=[],seen=new Set();
  const path=`/repos/Dollars-Archive/${repo}/releases`;
  let url=`https://api.github.com${path}?per_page=100`;
  while(url){
    const parsed=new URL(url);
    if(parsed.origin!=="https://api.github.com"||parsed.pathname!==path||seen.has(url)||seen.size>=20)throw new Error("Invalid pagination");
    seen.add(url);
    const response=await fetcher(url,{headers:{Accept:"application/vnd.github+json"},credentials:"omit",cache:force?"no-store":"default",signal:AbortSignal.timeout(15000)});
    if(!response.ok)throw new Error("GitHub unavailable");
    const releases=await response.json();if(!Array.isArray(releases))throw new Error("Invalid releases");
    for(const release of releases){
      if(release.draft||!/^v\d/.test(release.tag_name||""))continue;
      if(!Array.isArray(release.assets))throw new Error("Invalid assets");
      for(const asset of release.assets)assets.push({name:asset.name,tag:release.tag_name,asset_id:asset.id,downloads:asset.download_count});
    }
    const next=(response.headers.get("Link")||"").match(/<([^>]+)>;\s*rel="next"/);url=next?next[1]:"";
  }
  if(!validAssets(assets))throw new Error("Invalid counts");
  const result={at:now,assets};try{storage?.setItem(key,JSON.stringify(result))}catch(e){}
  return result;
}
async function refresh(patches,{fetcher=root.fetch,storage=null,now=Date.now(),minAt=0,force=false}={}){
  let cursor=0;const results=[];
  async function worker(){
    while(cursor<patches.length){
      const patch=patches[cursor++];
      try{
        const result=await fetchAssets(patch.repo,{fetcher,storage,now,minAt,force});
        patch.downloads=ledgerTotal(patch.repo,result.assets,patch.download_ledger||{});
        patch.downloads_current=result.assets.reduce((sum,a)=>sum+a.downloads,0);
        patch.downloads_carried=patch.downloads-patch.downloads_current;
        for(const asset of patch.assets){const live=result.assets.find(a=>a.tag===asset.tag&&a.name===asset.name);if(live)asset.downloads=live.downloads}
        results.push({repo:patch.repo,at:result.at});
      }catch(e){/* Retain the collected values on rate limits, timeouts and malformed responses. */}
    }
  }
  await Promise.all(Array.from({length:Math.min(3,patches.length)},()=>worker()));
  return results;
}
root.PatchDownloads={fetchAssets,ledgerTotal,refresh,TTL};
if(typeof module!=="undefined"&&module.exports)module.exports=root.PatchDownloads;
})(globalThis);
