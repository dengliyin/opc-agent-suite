const state={library:null,document:null,market:"",selected:new Set(),taskStatus:"idle"};
const $=selector=>document.querySelector(selector);
const documentSelect=$("#documentSelect"),marketSelect=$("#marketSelect"),voiceSelect=$("#voiceSelect");
const entriesHost=$("#entries"),generateButton=$("#generateButton"),summary=$("#summary");

function esc(value){return String(value).replace(/[&<>"']/g,char=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[char]));}
function currentEntries(){return state.document?.entries.filter(entry=>entry.market===state.market)||[];}
function matchingVoices(){return (state.library?.voices||[]).filter(voice=>voice.markets.includes(state.market));}
function renderDocuments(){
  const docs=state.library.documents;
  documentSelect.innerHTML=docs.length?docs.map(doc=>`<option value="${esc(doc.id)}">${esc(doc.product)} · ${doc.entries.length} 条</option>`).join(""):'<option value="">未找到可生成文案</option>';
  state.document=docs.find(doc=>doc.id===documentSelect.value)||docs[0]||null;
}
function renderMarkets(){
  const markets=[...new Map((state.document?.entries||[]).map(entry=>[entry.market,entry.country])).entries()];
  if(!markets.some(([market])=>market===state.market))state.market=markets[0]?.[0]||"";
  marketSelect.innerHTML=markets.map(([market,country])=>`<option value="${esc(market)}">${esc(market)} · ${esc(country)}</option>`).join("");
  marketSelect.value=state.market;
}
function renderVoices(){
  const voices=matchingVoices();
  voiceSelect.innerHTML=voices.length?voices.map(voice=>`<option value="${esc(voice.id)}">${esc(voice.name)}</option>`).join(""):'<option value="">当前国家暂无适配声音</option>';
}
function renderEntries(){
  const entries=currentEntries();
  state.selected=new Set([...state.selected].filter(id=>entries.some(entry=>entry.id===id)));
  summary.textContent=`${state.document?.product||"未选择产品"} · ${state.market||"未选择国家"} · 文案 ${entries.length} 条 · 已生成 ${entries.filter(entry=>entry.generated).length} 条`;
  entriesHost.innerHTML=entries.length?entries.map(entry=>`
    <article class="entry ${entry.generated?"generated":""}">
      <div class="entryHead">
        <input type="checkbox" data-entry="${esc(entry.id)}" ${state.selected.has(entry.id)?"checked":""}>
        <div><div class="entryTitle">${esc(entry.id)} · ${esc(entry.title)}</div>
          <div class="badges"><span class="badge">${esc(entry.market)}</span><span class="badge ${entry.generated?"done":"ready"}">${entry.generated?"已生成":"待生成"}</span></div>
        </div>
      </div>
      <div class="copy">${esc(entry.text)}</div>
      <div class="filename">${esc(entry.filename)}</div>
      ${entry.generated?`<audio controls preload="none" src="/api/audio?document=${encodeURIComponent(state.document.id)}&entry=${encodeURIComponent(entry.id)}"></audio>`:""}
    </article>`).join(""):'<div class="summary">当前国家没有符合“建议音频文件名＋音频文案”格式的内容。</div>';
  entriesHost.querySelectorAll("[data-entry]").forEach(input=>input.addEventListener("change",event=>{
    if(event.target.checked)state.selected.add(event.target.dataset.entry);else state.selected.delete(event.target.dataset.entry);
    updateButton();
  }));
  updateButton();
}
function updateButton(){generateButton.disabled=!state.selected.size||!voiceSelect.value||state.taskStatus==="running";}
function renderAll(){renderMarkets();renderVoices();renderEntries();$("#pathNote").textContent=`输出：${state.library.audio_root}/${state.document?.product||"<产品名>"}/`;}
async function loadLibrary(scan=false){
  const response=await fetch(scan?"/api/library?refresh=1":"/api/library");
  if(!response.ok)throw new Error("文案扫描失败");
  state.library=await response.json();
  const previous=state.document?.id;
  renderDocuments();
  if(previous&&state.library.documents.some(doc=>doc.id===previous)){documentSelect.value=previous;state.document=state.library.documents.find(doc=>doc.id===previous);}
  renderAll();
}
async function startGeneration(){
  const response=await fetch("/api/generate",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({
    document:state.document.id,entries:[...state.selected],voice:voiceSelect.value,overwrite:$("#overwriteInput").checked
  })});
  const data=await response.json();
  if(!response.ok)throw new Error(data.error||"任务创建失败");
  state.taskStatus="running";updateButton();pollStatus();
}
async function pollStatus(){
  const response=await fetch("/api/status"),task=await response.json();
  state.taskStatus=task.status;
  $("#taskMessage").textContent=task.message||task.status;
  $("#logs").textContent=(task.logs||[]).join("\n")||"暂无运行日志";
  $("#progress").className=`progress ${task.status}`;
  updateButton();
  if(task.status==="running"){setTimeout(pollStatus,1000);}
  else if(task.status==="completed"){state.selected.clear();await loadLibrary(true);}
}
documentSelect.addEventListener("change",()=>{state.document=state.library.documents.find(doc=>doc.id===documentSelect.value);state.market="";state.selected.clear();renderAll();});
marketSelect.addEventListener("change",()=>{state.market=marketSelect.value;state.selected.clear();renderAll();});
voiceSelect.addEventListener("change",updateButton);
$("#refreshButton").addEventListener("click",()=>loadLibrary(true).catch(error=>alert(error.message)));
$("#selectAllButton").addEventListener("click",()=>{currentEntries().filter(entry=>!entry.generated||$("#overwriteInput").checked).forEach(entry=>state.selected.add(entry.id));renderEntries();});
$("#clearButton").addEventListener("click",()=>{state.selected.clear();renderEntries();});
generateButton.addEventListener("click",()=>startGeneration().catch(error=>alert(error.message)));
loadLibrary().then(pollStatus).catch(error=>alert(error.message));
