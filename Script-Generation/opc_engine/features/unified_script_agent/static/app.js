const $=selector=>document.querySelector(selector);
const routeInputs=[...document.querySelectorAll('input[name="route"]')];
const modeInputs=[...document.querySelectorAll('input[name="mode"]')];
let state={sources:[],products:[],routes:{},country_languages:{},scan_index:{ready:false}};
let selectedJob=0;
let renderedRoute='';
const refreshedJobs=new Set();
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
  renderProducts();renderSources();renderMode();
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
  $('#sourceHint').textContent=source?source.path:(state.scan_index?.ready?'当前筛选没有脚本':'尚未建立索引，请点击“扫描资料库”');
  if(!source){$('#sourceStatus').innerHTML='';return}
  const status=source.status||{};
  $('#sourceStatus').innerHTML=`<span class="statusPill ${status.cloned?'done':'todo'}">${status.cloned?'已复刻':'未复刻'}</span><span class="statusPill mutation">裂变 ${Number(status.mutation_count||0)} 次</span>`;
  if(route()==='route1')$('#autoTargetProduct').textContent=source.product;
  if(source.market){$('#targetMarket').value=source.market;$('#targetLanguage').value=source.language||state.country_languages[source.market]||''}
}

function renderMode(){
  const mutation=mode()==='mutation';
  $('#variantField').style.display=mutation?'block':'none';
  $('#submitButton').textContent=mutation?'创建并执行裂变任务':'创建并执行复刻任务';
}

function renderState(){
  $('#modelStatus').textContent=`全局文本模型：${state.model?.text_model||'未配置'}${state.model?.has_api_key?' · API Key 已配置':' · 缺少 API Key'}`;
  const markets=Object.keys(state.country_languages||{});
  $('#targetMarket').innerHTML='<option value="">请选择</option>'+markets.map(code=>`<option value="${esc(code)}">${esc(code)}</option>`).join('');
  renderRoute();
  $('#scanButton').textContent=state.scan_index?.ready?'重新扫描':'扫描资料库';
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
function renderJobs(data){
  $('#queueStatus').textContent=`${data.running?'执行中':'空闲'} · 排队 ${data.queued}`;
  $('.jobsPanel').classList.toggle('idle',!data.jobs.length);
  if(!data.jobs.length){$('#jobs').innerHTML='<div class="empty">暂无任务</div>';$('#jobLog').textContent='';$('#outputs').innerHTML='';return}
  if(!selectedJob)selectedJob=data.jobs[0].id;
  $('#jobs').innerHTML=data.jobs.map(job=>`<div class="job ${job.id===selectedJob?'active':''}" data-id="${job.id}"><div class="jobTop"><b>#${job.id}</b><span class="jobStatus ${esc(job.status)}">${esc(statusText[job.status]||job.status)}</span></div><div class="jobTitle">${esc(job.title)}</div></div>`).join('');
  document.querySelectorAll('.job').forEach(item=>item.onclick=()=>{selectedJob=Number(item.dataset.id);renderJobs(data)});
  const active=data.jobs.find(job=>job.id===selectedJob)||data.jobs[0];
  $('#jobLog').textContent=[...(active.logs||[]),active.error?`错误：${active.error}`:''].filter(Boolean).join('\n')||'暂无日志';
  $('#jobLog').scrollTop=$('#jobLog').scrollHeight;
  const outputs=active.result?.outputs||[];
  $('#outputs').innerHTML=outputs.map(item=>`<div class="output">${item.reused?'复用':'新建'} · ${esc(item.name)}<br>${esc(item.path)}</div>`).join('');
  if(['completed','partial'].includes(active.status)&&!refreshedJobs.has(active.id)){refreshedJobs.add(active.id);loadState(false)}
}

async function loadJobs(){try{const response=await fetch('/api/jobs',{cache:'no-store'});const data=await response.json();if(response.ok)renderJobs(data)}catch(_error){}}

routeInputs.forEach(input=>input.onchange=renderRoute);
modeInputs.forEach(input=>input.onchange=renderMode);
$('#sourceProduct').onchange=renderScriptOptions;
$('#sourceScript').onchange=sourceChanged;
$('#targetMarket').onchange=()=>{$('#targetLanguage').value=state.country_languages[$('#targetMarket').value]||''};
$('#scanButton').onclick=()=>loadState(true);
$('#taskForm').onsubmit=createJob;
loadState(false);loadJobs();setInterval(loadJobs,2000);
