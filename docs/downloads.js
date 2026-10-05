/* Release and download refresh. Three workers, ten-minute cache, no credentials. */
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
  const key=`da-downloads:v2:${repo}`;
  try{const cache=JSON.parse(storage?.getItem(key)||"null");if(!force&&cache&&Array.isArray(cache.releases)&&cache.at>=minAt&&now-cache.at>=0&&now-cache.at<TTL&&validAssets(cache.assets))return cache}catch(e){}
  const assets=[],seen=new Set(),allReleases=[];
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
      allReleases.push({tag_name:release.tag_name,name:release.name,html_url:release.html_url,published_at:release.published_at,created_at:release.created_at,prerelease:!!release.prerelease,body:release.body,asset_count:release.assets.length});
      for(const asset of release.assets)assets.push({name:asset.name,tag:release.tag_name,asset_id:asset.id,downloads:asset.download_count,url:asset.browser_download_url,created_at:asset.created_at,release_published_at:release.published_at});
    }
    const next=(response.headers.get("Link")||"").match(/<([^>]+)>;\s*rel="next"/);url=next?next[1]:"";
  }
  if(!validAssets(assets))throw new Error("Invalid counts");
  const result={at:now,assets,releases:allReleases};try{storage?.setItem(key,JSON.stringify(result))}catch(e){}
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
        const latest=result.releases.filter(r=>!r.prerelease&&r.published_at&&/^v\d+(?:\.\d+)*$/.test(r.tag_name)).sort((a,b)=>b.published_at.localeCompare(a.published_at))[0];
        // Incomplete API fixtures/responses cannot replace valid collected metadata.
        if(latest&&typeof latest.html_url==='string'){
          patch.latest_release={tag:latest.tag_name,name:latest.name||latest.tag_name,url:latest.html_url,published_at:latest.published_at,asset_count:latest.asset_count};
          if(!patch.activity_at||latest.published_at>patch.activity_at)patch.activity_at=latest.published_at;
          if(patch.status==='wip')patch.status='released';
          if(result.assets.every(a=>typeof a.url==='string'))patch.assets=result.assets;
          const added=releaseAdditions(latest),v=latest.tag_name.slice(1);
          const entries=patch.changelog||[];
          if(added.length&&!entries.some(e=>sameVersion(e.v,v))){
            const date=new Date(latest.published_at).toLocaleDateString('sv-SE',{timeZone:'Asia/Seoul'});
            patch.changelog=[{v,date,date_source:'release',url:latest.html_url,added,partial:[],improved:[],fixed:[],note:''},...entries];
          }
          for(const key of added){
            const prior=patch.scope?.[key];patch.scope??={};
            patch.scope[key]={state:'done',since:prior?.state==='done'?prior.since:v};
          }
        }else for(const asset of patch.assets){const live=result.assets.find(a=>a.tag===asset.tag&&a.name===asset.name);if(live)asset.downloads=live.downloads}
        results.push({repo:patch.repo,at:result.at});
      }catch(e){/* Retain the collected values on rate limits, timeouts and malformed responses. */}
    }
  }
  await Promise.all(Array.from({length:Math.min(3,patches.length)},()=>worker()));
  return results;
}
function sameVersion(a,b){return String(a).replace(/^v/,'').split('.').map(Number).join('.').replace(/(?:\.0)+$/,'')===String(b).replace(/^v/,'').split('.').map(Number).join('.').replace(/(?:\.0)+$/,'')}
function releaseAdditions(release){
  const tag=release.tag_name.slice(1),sections=(release.body||'').split(/^##\s+(.+?)\s*$/m);
  let text='';for(let i=1;i<sections.length;i+=2)if(new RegExp('^v?'+tag.replace(/\./g,'\\.')+'(?:\\s|$)').test(sections[i]))text+='\n'+sections[i+1];
  const intro=new RegExp('^v?'+tag.replace(/\./g,'\\.')+'(?:에는|에서|\\s)');
  text+='\n'+sections[0].split('\n').filter(l=>intro.test(l)).join('\n');
  const lines=text.split('\n').filter(l=>(/^\s*[-*]\s+/.test(l)||intro.test(l))&&/추가|한글화|한국어화|완료/.test(l)&&!/예정|미완료|미작업|일부|미포함|제외/.test(l));
  const labels={title:/타이틀(?: 한글화)?/,ui:/메뉴[·/ ]*UI/i,dialogue:/대사(?: 전체)?\s*(?:추가|한글화|한국어화|완료)/,image:/이미지(?: 번역)?/,video:/(?:동영상|영상|오프닝|엔딩).*자막/};
  return Object.entries(labels).filter(([key,re])=>lines.some(l=>re.test(l))).map(([key])=>key);
}
root.PatchDownloads={fetchAssets,ledgerTotal,refresh,releaseAdditions,TTL};
if(typeof module!=="undefined"&&module.exports)module.exports=root.PatchDownloads;
})(globalThis);
