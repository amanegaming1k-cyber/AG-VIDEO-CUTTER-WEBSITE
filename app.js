const API_BASE = ""; // Same-origin Flask backend
const CHUNK_SIZE = 4 * 1024 * 1024; // 4 MiB chunks: smaller requests are friendlier to mobile networks.
const $ = (id) => document.getElementById(id);
const dropZone = $("dropZone"), fileInput = $("fileInput"), startButton = $("startButton");
const selectedFile = $("selectedFile"), statusArea = $("statusArea"), results = $("results");
let selected = null, activeJob = null, cancelled = false, partUrls = [];

function formatBytes(n){if(!Number.isFinite(n))return "Unknown size";const units=["B","KB","MB","GB","TB"];let i=0;while(n>=1024&&i<units.length-1){n/=1024;i++}return `${n.toFixed(i?1:0)} ${units[i]}`}
function setProgress(percent,text,detail){$("progressBar").style.width=`${Math.max(0,Math.min(100,percent))}%`;$("percentText").textContent=`${Math.round(percent)}%`;if(text)$("statusText").textContent=text;if(detail)$("statusDetail").textContent=detail}
function showStatus(){statusArea.classList.remove("hidden");results.classList.add("hidden")}
function resetJob(){cancelled=false;activeJob=null;partUrls.forEach(URL.revokeObjectURL);partUrls=[];statusArea.classList.add("hidden");results.classList.add("hidden");startButton.disabled=!selected}
function chooseFile(file){if(!file)return;selected=file;$("fileName").textContent=file.name;$("fileSize").textContent=formatBytes(file.size);selectedFile.classList.remove("hidden");startButton.disabled=false;results.classList.add("hidden")}
dropZone.addEventListener("click",()=>fileInput.click());
dropZone.addEventListener("keydown",e=>{if(e.key==="Enter"||e.key===" "){e.preventDefault();fileInput.click()}});
fileInput.addEventListener("change",()=>chooseFile(fileInput.files[0]));
$("removeFile").addEventListener("click",()=>{selected=null;fileInput.value="";selectedFile.classList.add("hidden");startButton.disabled=true;resetJob()});
for(const ev of ["dragenter","dragover"])dropZone.addEventListener(ev,e=>{e.preventDefault();dropZone.classList.add("dragover")});
for(const ev of ["dragleave","drop"])dropZone.addEventListener(ev,e=>{e.preventDefault();dropZone.classList.remove("dragover")});
dropZone.addEventListener("drop",e=>chooseFile(e.dataTransfer.files[0]));
$("cancelButton").addEventListener("click",()=>{cancelled=true;$("statusText").textContent="Cancellation requested…";$("statusDetail").textContent="Stopping the current upload or processing job."});

async function request(path,options={}){const response=await fetch(API_BASE+path,options);let data={};try{data=await response.json()}catch{}if(!response.ok)throw new Error(data.error||`Server error (${response.status})`);return data}
async function uploadChunked(file,jobId){
  const total=Math.ceil(file.size/CHUNK_SIZE);
  for(let index=0;index<total;index++){
    if(cancelled)throw new Error("Cancelled by user.");
    const chunk=file.slice(index*CHUNK_SIZE,Math.min(file.size,(index+1)*CHUNK_SIZE));
    const form=new FormData();form.append("chunk",chunk,"chunk.bin");
    await request(`/api/upload/${jobId}/${index}`,{method:"POST",body:form});
    setProgress(((index+1)/total)*65,`Uploading video · chunk ${index+1}/${total}`,`${formatBytes(Math.min(file.size,(index+1)*CHUNK_SIZE))} of ${formatBytes(file.size)} uploaded`);
  }
  return request(`/api/upload/${jobId}/complete`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:file.name,size:file.size,total_chunks:total})});
}
async function waitForProcessing(jobId){
  while(!cancelled){
    const state=await request(`/api/status/${jobId}`);
    const p=Math.min(98,65+(state.progress||0)*0.33);
    setProgress(p,state.message||"Splitting video…",state.detail||"Please keep this page open.");
    if(state.status==="done")return state;
    if(state.status==="error")throw new Error(state.error||"Video processing failed.");
    await new Promise(r=>setTimeout(r,1200));
  }
  throw new Error("Cancelled by user.");
}
function renderParts(parts){
  const list=$("partsList");list.innerHTML="";
  parts.forEach((part,i)=>{
    const row=document.createElement("div");row.className="part";
    const number=document.createElement("span");number.className="part-number";number.textContent=String(i+1).padStart(2,"0");
    const info=document.createElement("div");info.className="part-info";
    const name=document.createElement("b");name.textContent=part.filename||`part_${i+1}.mp4`;
    const meta=document.createElement("small");meta.textContent=part.duration?`Duration: ${part.duration}`:"MP4 video";
    info.append(name,meta);
    const link=document.createElement("a");link.href=part.url;link.download=part.filename||`part_${i+1}.mp4`;link.textContent="Download";
    row.append(number,info,link);list.append(row);
  });
  $("downloadAll").onclick=async()=>{for(const part of parts){const a=document.createElement("a");a.href=part.url;a.download=part.filename;document.body.append(a);a.click();a.remove();await new Promise(r=>setTimeout(r,500))}};
}
startButton.addEventListener("click",async()=>{
  if(!selected||activeJob)return;
  cancelled=false;startButton.disabled=true;showStatus();setProgress(0,"Starting upload…","Your video is uploaded in small chunks to reduce individual request size.");
  try{
    const init=await request("/api/start",{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({filename:selected.name,size:selected.size})});
    activeJob=init.job_id;
    await uploadChunked(selected,activeJob);
    if(cancelled)throw new Error("Cancelled by user.");
    setProgress(66,"Video uploaded · starting FFmpeg","The server is checking the video and creating four equal-duration clips.");
    const done=await waitForProcessing(activeJob);
    renderParts(done.parts);setProgress(100,"Completed successfully","All four parts are ready to download.");results.classList.remove("hidden");
  }catch(err){setProgress(0,"Could not complete",err.message||"Unknown error");$("statusDetail").textContent=`${err.message||"Unknown error"} — Check the server logs if the problem continues.`}
  finally{activeJob=null;startButton.disabled=!selected}
});
