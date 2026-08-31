const $=selector=>document.querySelector(selector);
const routeInputs=[...document.querySelectorAll('input[name="route"]')];
const modeInputs=[...document.querySelectorAll('input[name="mode"]')];
let state={sources:[],products:[],routes:{},country_languages:{},scan_index:{ready:false}};
let selectedJob=0;
let renderedRoute='';
let sourcePreviewRequest=0;
const refreshedJobs=new Set();
const routeTitles={route1:'线路 1 · 爆款复刻',route2:'线路 2 · 产品脚本改写',route3:'线路 3 · AI＋实拍混剪'};
const esc=value=>String(value??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const selectedValue=inputs=>inputs.find(input=>input.checked)?.value||'';

function route(){return selectedValue(routeInputs)}
function mode(){return selectedValue(modeInputs)}
function sourceList(){const sourceRoute=route()==='route3'?'route3':'route1';return state.sources.filter(item=>item.route===sourceRoute)}
function currentSource(){return state.sources.find(item=>item.path===$('#sourceScript').value)}

function renderRoute(){
  const current=state.routes[route()]||{};
  $('#pathBox').innerHTML=`<div class="pathRow"><b>业务输入</b><span>${esc(current.input||'')}</span></div><div class="pathRow"><b>最终输出</b><span>${esc(current.output||'')}</span></div><div class="pathRow"><b>产品资料</b><span>${esc(current.product_fact||'')}</span></div>`;
  $('#productRule').textContent=current.product_fact||'';
  $('#productFactSummary').textContent=current.product_fact||'按当前线路自动读取';
  renderProducts();renderSources();renderMode();renderTaskSummary();
}

function renderProducts(){
  const automatic=route()==='route1';
  $('#autoProduct').hidden=!automatic;
  $('#targetProductField').hidden=automatic;
  if(automatic){$('#targetProduct').innerHTML='';const source=currentSource();$('#autoTargetProduct').textContent=source?.product||$('#sourceProduct').value||'请选择来源产品';renderedRoute=route();return}
  const routeChanged=renderedRoute&&renderedRoute!==route();
  const old=route()==='route3'&&routeChanged?'':$('#targetProduct').value;
  const optional=route()==='route3';
  $('#targetProduct').innerHTML=(optional?'<option value="">不参考产品资料（沿用来源脚本）</option>':'<option value="">请选择目标产品</option>')+state.products.map(item=>`<option value="${esc(item.name)}">${esc(item.name)}</option>`).join('');
  if([...$('#targetProduct').options].some(option=>option.value===old))$('#targetProduct').value=old;
  renderedRoute=route();
}

function renderSources(){
  const sources=sourceList();
  const previousProduct=$('#sourceProduct').value;
  const products=[...new Set(sources.map(item=>item.product).filter(Boolean))].sort((a,b)=>a.localeCompare(b,'zh-CN'));
  $('#sourceProduct').innerHTML=products.length?products.map(name=>`<option value="${esc(name)}">${esc(name)}</option>`).join(''):'<option value="">暂无索引，请扫描资料库</option>';
  if(products.includes(previousProduct))$('#sourceProduct').value=previousProduct;
  renderScriptOptions();
}

function renderScriptOptions(){
  const product=$('#sourceProduct').value;
  const old=$('#sourceScript').value;
  const sources=sourceList().filter(item=>item.product===product);
  $('#sourceScript').innerHTML=sources.length?sources.map(item=>{const status=item.status||{};const label=`${item.content_type==='纯AI'?'':item.content_type+' · '}${item.name} · ${status.cloned?'已复刻':'未复刻'} · 裂变 ${Number(status.mutation_count||0)} 次`;return `<option value="${esc(item.path)}">${esc(label)}</option>`}).join(''):'<option value="">该产品暂无脚本</option>';
  if(sources.some(item=>item.path===old))$('#sourceScript').value=old;
  sourceChanged();
}

function sourceChanged(){
  const source=currentSource();
  loadSourcePreview(source);
  if(!source){$('#sourceStatus').innerHTML='';renderTaskSummary();return}
  const status=source.status||{};
  $('#sourceStatus').innerHTML=`<span class="statusPill ${status.cloned?'done':'todo'}">${status.cloned?'已复刻':'未复刻'}</span><span class="statusPill mutation">裂变 ${Number(status.mutation_count||0)} 次</span>`;
  if(route()==='route1')$('#autoTargetProduct').textContent=source.product;
  if(source.market){$('#targetMarket').value=source.market;$('#targetLanguage').value=source.language||state.country_languages[source.market]||''}
  renderTaskSummary();
}

async function loadSourcePreview(source){
  const request=++sourcePreviewRequest;
  if(!source){
    $('#sourcePreviewStatus').textContent='请选择来源脚本';
    $('#sourcePreviewPath').textContent='';
    $('#sourcePreview').textContent='选择来源脚本后在这里显示 Markdown 全文';
    return;
  }
  $('#sourcePreviewStatus').textContent='正在读取…';
  $('#sourcePreviewPath').textContent=source.path;
  $('#sourcePreview').textContent='正在读取脚本内容…';
  const query=new URLSearchParams({route:route(),path:source.path});
  try{
    const response=await fetch(`/api/source-preview?${query}`,{cache:'no-store'});
    const data=await response.json();
    if(!response.ok)throw new Error(data.error||'读取失败');
    if(request!==sourcePreviewRequest)return;
    $('#sourcePreviewStatus').textContent=data.name;
    $('#sourcePreviewPath').textContent=data.path;
    $('#sourcePreview').textContent=data.content||'（空文件）';
    $('#sourcePreview').scrollTop=0;
  }catch(error){
    if(request!==sourcePreviewRequest)return;
    $('#sourcePreviewStatus').textContent='读取失败';
    $('#sourcePreview').textContent=error.message;
  }
}

function renderMode(){
  const mutation=mode()==='mutation';
  $('#variantCount').disabled=!mutation;
  $('#variantField').classList.toggle('disabled',!mutation);
  $('#submitButton').innerHTML=mutation?'▷&nbsp; 创建并执行裂变任务':'▷&nbsp; 创建并执行复刻任务';
  renderTaskSummary();
}

function renderTaskSummary(){
  const source=currentSource();
  const language=$('#targetLanguage')?.value||'未选择语言';
  const model=$('#targetModel')?.selectedOptions?.[0]?.textContent||'Omni（已开放）';
  const targetProduct=$('#targetProduct')?.value||'';
  const missingTarget=route()==='route2'&&!targetProduct;
  const product=route()==='route1'?(source?.product||$('#sourceProduct')?.value||'未选择产品'):route()==='route2'?(targetProduct||'未选择目标产品'):(targetProduct||'不参考产品资料');
  const action=mode()==='mutation'?`裂变 × ${Number($('#variantCount')?.value||1)}`:'复刻';
  $('#taskSummary').textContent=`${routeTitles[route()]||''} ｜ ${action} ｜ ${product||'未选择产品'} ｜ ${language} ｜ ${model}`;
  $('#productReadyCell').classList.toggle('ready',!missingTarget);
  $('#productReadyCell').classList.toggle('pending',missingTarget);
  $('#productReadyStatus').textContent=missingTarget?'○ 待选择':'◎ 已就绪';
  $('#formMessage').textContent=!source?'请选择来源脚本':missingTarget?'请选择目标产品':'准备就绪，可以创建任务';
}

function renderState(){
  $('#modelStatus').textContent=`全局文本模型：${state.model?.text_model||'未配置'}${state.model?.has_api_key?' · API Key 已配置':' · 缺少 API Key'}`;
  const markets=Object.keys(state.country_languages||{});
  $('#targetMarket').innerHTML='<option value="">请选择</option>'+markets.map(code=>`<option value="${esc(code)}">${esc(code)}</option>`).join('');
  renderRoute();
  $('#scanButton').textContent=state.scan_index?.ready?'↻ 重新扫描':'↻ 扫描资料库';
}

async function loadState(refresh=false){
  $('#scanButton').disabled=refresh;
  if(refresh)$('#scanButton').textContent='正在扫描…';
  try{const response=await fetch(`/api/state${refresh?'?refresh=1':''}`,{cache:'no-store'});const data=await response.json();if(!response.ok)throw new Error(data.error||'读取失败');state=data;renderState()}
  catch(error){$('#formMessage').textContent=error.message}
  finally{$('#scanButton').disabled=false}
}

async function createJob(event){
  event.preventDefault();
  const source=currentSource();
  if(!source){$('#formMessage').textContent='请先选择来源脚本';return}
  const payload={route:route(),mode:mode(),source_path:source.path,target_product:route()==='route1'?source.product:$('#targetProduct').value,target_market:$('#targetMarket').value,target_language:$('#targetLanguage').value,model:'omni',variant_count:Number($('#variantCount').value||1)};
  $('#submitButton').disabled=true;$('#formMessage').textContent='正在创建任务…';
  try{const response=await fetch('/api/jobs',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify(payload)});const data=await response.json();if(!response.ok)throw new Error(data.error||'创建失败');selectedJob=data.job.id;$('#formMessage').textContent=`任务 #${selectedJob} 已加入队列`;await loadJobs()}
  catch(error){$('#formMessage').textContent=error.message}
  finally{$('#submitButton').disabled=false}
}

const statusText={queued:'排队中',running:'执行中',completed:'已完成',partial:'部分完成',failed:'失败',interrupted:'已中断'};
function relativeTime(job){
  const timestamp=job.finished_at||job.started_at||job.created_at;
  if(!timestamp)return'';
  const seconds=Math.max(0,Math.floor(Date.now()/1000-Number(timestamp)));
  if(seconds<60)return'刚刚';
  if(seconds<3600)return`${Math.floor(seconds/60)} 分钟前`;
  if(seconds<86400)return`${Math.floor(seconds/3600)} 小时前`;
  return`${Math.floor(seconds/86400)} 天前`;
}
function renderJobs(data){
  $('#queueStatus').textContent=`${data.running?'执行中':'空闲'} · 排队 ${data.queued}`;
  $('.jobsPanel').classList.toggle('idle',!data.jobs.length);
  if(!data.jobs.length){$('#jobs').innerHTML='<div class="empty">暂无任务</div>';$('#jobLog').textContent='暂无任务日志';$('#selectedJobStatus').textContent='当前未选择任务';return}
  if(!selectedJob)selectedJob=data.jobs[0].id;
  $('#jobs').innerHTML=data.jobs.map(job=>`<div class="job ${job.id===selectedJob?'active':''}" data-id="${job.id}"><b class="jobNumber">#${job.id}</b><span class="jobTitle">${esc(job.title)}</span><span class="jobStatus ${esc(job.status)}">${esc(statusText[job.status]||job.status)}</span><span class="jobAge">${esc(relativeTime(job))}</span><span class="jobArrow">›</span></div>`).join('');
  document.querySelectorAll('.job').forEach(item=>item.onclick=()=>{selectedJob=Number(item.dataset.id);renderJobs(data)});
  const active=data.jobs.find(job=>job.id===selectedJob)||data.jobs[0];
  $('#selectedJobStatus').textContent=`当前所选任务：#${active.id}`;
  $('#jobLog').textContent=[...(active.logs||[]),active.error?`错误：${active.error}`:''].filter(Boolean).join('\n')||'暂无日志';
  $('#jobLog').scrollTop=$('#jobLog').scrollHeight;
  if(['completed','partial'].includes(active.status)&&!refreshedJobs.has(active.id)){refreshedJobs.add(active.id);loadState(false)}
}

async function loadJobs(){try{const response=await fetch('/api/jobs',{cache:'no-store'});const data=await response.json();if(response.ok)renderJobs(data)}catch(_error){}}

function showDetail(name){
  const source=name==='source';
  $('#logTab').classList.toggle('active',!source);
  $('#sourceTab').classList.toggle('active',source);
  $('#logView').hidden=source;
  $('#sourceView').hidden=!source;
}

routeInputs.forEach(input=>input.onchange=renderRoute);
modeInputs.forEach(input=>input.onchange=renderMode);
$('#sourceProduct').onchange=renderScriptOptions;
$('#sourceScript').onchange=sourceChanged;
$('#targetMarket').onchange=()=>{$('#targetLanguage').value=state.country_languages[$('#targetMarket').value]||'';renderTaskSummary()};
$('#targetLanguage').oninput=renderTaskSummary;
$('#targetProduct').onchange=renderTaskSummary;
$('#targetModel').onchange=renderTaskSummary;
$('#variantCount').oninput=renderTaskSummary;
$('#logTab').onclick=()=>showDetail('log');
$('#sourceTab').onclick=()=>showDetail('source');
$('#scanButton').onclick=()=>loadState(true);
$('#taskForm').onsubmit=createJob;
loadState(false);loadJobs();setInterval(loadJobs,2000);
