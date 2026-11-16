"use strict";
console.info("CU-BEMS dashboard restored dates with working manager notes loaded");
let activeRecords=[];
let lastForecastData=null;
let previousActivityMode=null;
let validDates={};
let activeMode="historical";
// One app serves both the dashboard and the API, so call the same address as the page.
// (If opened from the old separate static server on port 5173, use the API on port 8001.)
const API_BASE = window.location.port === "5173" ? `${window.location.protocol}//${window.location.hostname}:8001` : window.location.origin;
const byId = (id) => document.getElementById(id);
const numberFmt = new Intl.NumberFormat("en-US", {maximumFractionDigits:2});
const dateLabel = (value) => value ? new Date(value).toLocaleString("en-GB", {year:"numeric",month:"short",day:"numeric",hour:"2-digit",minute:"2-digit",hour12:false}) : "—";
const escapeHtml = (value) => String(value).replace(/[&<>"']/g, (ch) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[ch]));
function setMessage(message, state="") { const el=byId("message"); el.textContent=message; el.className=`message ${state}`.trim(); }
function setBusy(busy) {byId("demoButton").disabled=busy;byId("simButton").disabled=busy; byId("exploreButton").disabled=busy; byId("csvInput").disabled=busy;byId("demoButton").textContent=busy?"Loading…":"2019 real data";byId("simButton").textContent=busy?"Running…":"▶ Simulate 2026";}
async function checkHealth(){const el=byId("apiStatus");try{let r=await fetch(`${API_BASE}/health`,{signal:AbortSignal.timeout(6000)});if(!r.ok)throw new Error("Health check failed");const data=await r.json();el.textContent=`● API connected · ${data.models_loaded} models`;el.className="status online";}catch(e){el.textContent="● API offline";el.className="status offline";}}
async function sendForecast(endpoint, options){setBusy(true);setMessage("Generating predictions from the saved LightGBM models…");try{const response=await fetch(`${API_BASE}${endpoint}`,options);const data=await response.json();if(!response.ok){throw new Error(typeof data.detail==="string"?data.detail:JSON.stringify(data.detail||data));}if(!Array.isArray(data.forecasts)||data.forecasts.length!==4)throw new Error("Unexpected API response: four forecasts were expected");activeMode=data.data_mode==="simulation"?"simulation":(endpoint.includes("upload")?"upload":"historical");lastForecastData=data;
if(previousActivityMode!==activeMode){byId("activityDate").value=data.forecast_origin.slice(0,10);previousActivityMode=activeMode;}
await loadActivities();renderData(data);renderHistory(data);renderMode(data);byId("originInput").value=data.forecast_origin.slice(0,16);setMessage(activeMode==="simulation"?"Simulation complete. These are model outputs from synthetic 2026 input data, not actual electricity readings.":"Forecast generated successfully from your trained CU-BEMS models.","success");}catch(err){let msg=err.message||"Unknown error";if(msg.toLowerCase().includes("failed to fetch"))msg="Cannot connect to the forecasting API. Start the app (see README) and open it from its web address, not as a file.";setMessage(msg,"error");}finally{setBusy(false);}}
function matchingActivities(targetDatetime) {
  if (!targetDatetime) return [];
  const day=targetDatetime.slice(0,10), time=targetDatetime.slice(11,16);
  return activeRecords.filter(r=>r.day===day && r.start_time<=time && time<r.end_time);
}
function describeHorizon(forecast, comparison) {
 const kw=Number(forecast.predicted_demand_kw);
 if(!Number.isFinite(kw))return {tone:"neutral", title:"Unavailable", explanation:"No prediction available.", action:"Check readings and try again."};
 const holiday=Boolean(forecast.target_is_holiday);
 const valid=comparison&&Number(comparison.reference_count)>=4&&Number(comparison.reference_median_kw)>0;
 const difference=valid?(kw/Number(comparison.reference_median_kw)-1)*100:null;
 let tone="neutral", title="Not enough history", explanation="Not enough past readings for a comparison.", action="Review planned activities and available readings.";
 if(valid) {
   if(comparison.above_usual_high || difference>10){tone="high";title="Higher than usual";explanation="This hour may use more electricity than normal.";action="Check busy rooms and equipment schedules. Review avoidable usage if practical.";}
   else if(difference < -10){tone="low";title="Lower than usual";explanation="Less electricity is expected than normal.";action="Keep routine monitoring; confirm building services remain available.";}
   else {tone="normal";title="Close to normal";explanation="Electricity demand looks typical for this hour.";action="No extra action needed unless an event is planned.";}
 }
 if(holiday){
   if(tone!=="high") {tone="holiday";title="Holiday period";}
   explanation+=" This date is marked as a public holiday.";
   action="Check rooms in use, lighting and cooling schedules. Keep essential services on.";
 }
 return {tone,title,explanation,action};
}
function renderData(data) {
 const rows=data.forecasts.slice().sort((a,b)=>a.horizon_hours-b.horizon_hours);
 const comparisons=new Map((data.insights?.forecast_comparisons||[]).map(x=>[Number(x.horizon_hours),x]));
 byId("forecastCards").innerHTML=rows.map(f=>{
   const h=Number(f.horizon_hours), info=describeHorizon(f,comparisons.get(h));
   const activities=matchingActivities(f.target_datetime);
   const context=activities.length?`<div class="manager-context"><strong>Manager's plan</strong>${activities.map(r=>`<p>${escapeHtml(r.category)} · ${escapeHtml(r.start_time)}–${escapeHtml(r.end_time)}${r.notes?` · ${escapeHtml(r.notes)}`:""}</p>`).join("")}<small>Recorded by manager; not a verified cause or an input to the trained model.</small></div>`:"";
   return `<article class="forecast-card-v5 tone-${info.tone}">
     <div class="forecast-v5-head"><span class="forecast-v5-horizon">In ${h} ${h===1?"hour":"hours"}</span><span class="forecast-v5-pill">${escapeHtml(info.title)}</span></div>
     <div class="forecast-v5-number">${numberFmt.format(f.predicted_demand_kw)} <small>kW</small></div>
     <div class="forecast-v5-date">${escapeHtml(dateLabel(f.target_datetime))}</div>
     <p class="forecast-brief">${escapeHtml(info.explanation)}</p>
     ${context}
     <div class="forecast-v5-action"><strong>What to do</strong><p>${escapeHtml(activities.length?"Prepare lighting, cooling and staffing for the recorded activity. "+info.action:info.action)}</p></div>
   </article>`;
 }).join("");
 byId("detailOrigin").textContent=dateLabel(data.forecast_origin);
 const n=Number(data.skipped_trailing_missing_hours||0);
 const historical=data.data_mode!=="simulation" && new Date(data.forecast_origin).getFullYear()<new Date().getFullYear();
 byId("qualityContent").innerHTML=`
   <p><strong>Forecast starts:</strong> ${escapeHtml(dateLabel(data.forecast_origin))}</p>
   <p><strong>Historical readings unavailable:</strong> ${numberFmt.format(data.missing_historical_demand_hours||0)} time slots. Missing readings are not treated as zero.</p>
   ${n?`<p>${numberFmt.format(n)} trailing hours lacked valid readings. Forecasting uses the most recent valid hour.</p>`:""}
   ${historical?'<p>This is a historical demo using 2019 data, not live monitoring.</p>':''}`;
 drawChart(rows);
}
function drawChart(rows){const values=rows.map(r=>Number(r.predicted_demand_kw));if(values.some(v=>!Number.isFinite(v))){byId("chart").textContent="Cannot plot non-finite forecasts";return;}const max=Math.max(1,...values)*1.15;const w=900,h=290,left=68,right=25,top=20,bottom=57,base=h-bottom,chartH=base-top,innerW=w-left-right;const x=(i)=>left+(i+.5)*innerW/rows.length;const y=(v)=>base-v/max*chartH;let svg=`<svg class="chart-svg" role="img" aria-label="Bar chart of building demand forecasts" viewBox="0 0 ${w} ${h}">`;for(let i=0;i<=4;i++){const v=max*i/4,yy=y(v);svg+=`<line x1="${left}" y1="${yy}" x2="${w-right}" y2="${yy}" stroke="#e4ecec"/><text x="${left-10}" y="${yy+4}" text-anchor="end" font-size="12" fill="#81969a">${Math.round(v)}</text>`;}const bw=Math.min(110,innerW/rows.length*.48);rows.forEach((r,i)=>{const v=values[i],xx=x(i),yy=y(v);svg+=`<rect x="${xx-bw/2}" y="${yy}" width="${bw}" height="${Math.max(0,base-yy)}" rx="6" fill="#23866f"/><text x="${xx}" y="${Math.max(13,yy-10)}" text-anchor="middle" font-weight="700" font-size="13" fill="#28515b">${numberFmt.format(v)}</text><text x="${xx}" y="${base+24}" text-anchor="middle" font-size="13" fill="#69818a">${r.horizon_hours}h ahead</text>`;});svg+=`</svg>`;byId("chart").innerHTML=svg;}
const jsonOptions = (payload) => ({method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
byId("demoButton").addEventListener("click",()=>sendForecast("/analyze/demo",jsonOptions({})));
byId("simButton").addEventListener("click",()=>sendForecast("/analyze/simulated",jsonOptions({})));
byId("exploreButton").addEventListener("click",()=>{
 const origin=byId("originInput").value;
 if(!origin){setMessage("Choose a date and hour first.","error");return;}
 sendForecast(activeMode==="simulation"?"/analyze/simulated":"/analyze/demo",jsonOptions({origin:origin.length===16?origin+":00":origin}));
});
byId("rangeSelect").addEventListener("change",()=>{if(window.lastHistory) renderHistoryChart(window.lastHistory);});
byId("csvInput").addEventListener("change",async (e)=>{const file=e.target.files[0];if(!file)return;if(!file.name.toLowerCase().endsWith(".csv")){setMessage("Select a .csv file.","error");return;}if(file.size>20*1024*1024){setMessage("CSV exceeds the 20 MB upload limit.","error");return;}const form=new FormData();form.append("file",file);await sendForecast("/analyze/upload",{method:"POST",body:form});e.target.value="";});
function readable(v){return v===null||v===undefined||!Number.isFinite(Number(v))?"Unavailable":numberFmt.format(v)+" kW";}
function renderHistory(data){
  const m=data.observations||{};
  byId("currentDemand").textContent=readable(m.current_kw);
  byId("nowDatetime").textContent=(data.data_mode==="simulation"?"Simulated for ":"Measured on ")+dateLabel(data.forecast_origin)+(data.data_mode==="simulation"?" · NOT a live reading":" · historical CU-BEMS data");
  byId("previousHour").textContent=readable(m.previous_hour_kw);
  byId("yesterday").textContent=readable(m.same_hour_yesterday_kw);
  byId("dailyMean").textContent=readable(m.last_24h_average_kw);
  const current=m.current_kw===null||m.current_kw===undefined?NaN:Number(m.current_kw);
  const yesterday=m.same_hour_yesterday_kw===null||m.same_hour_yesterday_kw===undefined?NaN:Number(m.same_hour_yesterday_kw);
  const summary=byId("historyComparison");
  if(Number.isFinite(current)&&Number.isFinite(yesterday)&&yesterday>0){
    const change=(current/yesterday-1)*100;
    const direction=Math.abs(change)<5?"close to":change<0?"lower than":"higher than";
    summary.textContent=Math.abs(change)<5 ? "About the same ("+Math.abs(change).toFixed(1)+"% difference)" : Math.abs(change).toFixed(1)+"% "+direction+" yesterday";
    summary.className="measured-comparison "+(change>10?"compare-up":change<-10?"compare-down":"compare-steady");
  } else {
    summary.textContent="Not enough measurements to compare";
    summary.className="measured-comparison";
  }
  // Date and hour selectors are populated from available observations by loadAvailableTimes().
  window.lastHistory=data.history||[];
  const total=window.lastHistory.length;
  byId("historyNote").textContent=`${m.history_valid_points??0} available hours in the past ${m.history_window_hours??168} hours (including current). Last-24h average is based on ${m.last_24h_valid_hours??0} observed hours. Missing hours are never treated as zero.`;
  renderHistoryChart(window.lastHistory);
}
function renderHistoryChart(history){
  const n=Number(byId("rangeSelect").value||168);
  const rows=history.slice(-(n+1));
  const el=byId("historyChart");
  if(!rows.length){el.textContent="No historical observations returned.";return;}
  const vals=rows.map(x=>x.actual_demand_kw===null?null:Number(x.actual_demand_kw));
  const finite=vals.filter(Number.isFinite);
  if(!finite.length){el.textContent="This period has no measured demand.";return;}
  const w=970,h=310,left=64,right=20,top=24,base=258,hi=Math.max(1,...finite)*1.12,inner=w-left-right;
  const x=i=>left+i*inner/Math.max(1,rows.length-1);
  const y=v=>base-v/hi*(base-top);
  let svg=`<svg class="history-svg" viewBox="0 0 ${w} ${h}" role="img" aria-label="Historical measured energy demand over selected hours, with gaps where readings are missing">`;
  for(let i=0;i<=4;i++){let v=hi*i/4,yy=y(v);svg+=`<line x1="${left}" y1="${yy}" x2="${w-right}" y2="${yy}" stroke="#e4ecec"/><text x="${left-12}" y="${yy+4}" text-anchor="end" font-size="12" fill="#799098">${Math.round(v)}</text>`;}
  let line=[];
  const flush=()=>{if(line.length>1)svg+=`<polyline fill="none" stroke="#218975" stroke-width="2.8" stroke-linecap="round" stroke-linejoin="round" points="${line.join(" ")}"/>`;line=[];};
  rows.forEach((r,i)=>{const v=vals[i];if(v===null||!Number.isFinite(v)){flush();return;}line.push(`${x(i).toFixed(2)},${y(v).toFixed(2)}`);});flush();
  let stride=Math.max(1,Math.ceil(rows.length/40));
  rows.forEach((r,i)=>{const v=vals[i];if(v===null||!Number.isFinite(v)||i%stride!==0&&i!==rows.length-1)return;svg+=`<circle cx="${x(i).toFixed(2)}" cy="${y(v).toFixed(2)}" r="3.5" fill="#218975"><title>${escapeHtml(dateLabel(r.datetime))}: ${numberFmt.format(v)} kW measured</title></circle>`;});
  for(let i=0;i<5;i++){const j=Math.round((rows.length-1)*i/4);svg+=`<text x="${x(j)}" y="${base+28}" text-anchor="middle" font-size="11" fill="#799098">${escapeHtml(rows[j].datetime.slice(5,16).replace("T"," "))}</text>`;}
  svg+=`<text x="${left}" y="${h-7}" font-size="10" fill="#8b9ba2">Missing readings are displayed as breaks in the line</text></svg>`;
  el.innerHTML=svg;
}
checkHealth();


function renderMode(data){
 const sim=data.data_mode==="simulation";
 const banner=byId("modeBanner");
 banner.className="mode-banner "+(sim?"simulation":"historical");
 banner.innerHTML=sim
  ? "<strong>SIMULATED 2026 — NOT LIVE.</strong> Readings are artificial examples based on altered 2019 demand patterns. Forecasts are actual model outputs from those synthetic inputs, not verified 2026 demand."
  : "<strong>REAL HISTORICAL DATA.</strong> These are 2019 CU-BEMS measurements. Predictions show what the trained models forecast from the selected historical starting hour.";
 byId("dataBadge").textContent=sim?"SIMULATED 2026 · not live":"Measured CU-BEMS · 2019";
 byId("historyBadge").textContent=sim?"Synthetic input history · kW":"2019 historical readings · kW";
 byId("sourceData").textContent=sim?"Synthetic data · November 2026":"CU-BEMS · 2019";
 byId("sourceNote").textContent=sim?"Demo-only, modified historical patterns":"Historical building sensor measurements";
}


function formatGregorianDay(day){const [y,m,d]=String(day).slice(0,10).split("-").map(Number);if(!y||!m||!d)return String(day);return new Date(Date.UTC(y,m-1,d)).toLocaleDateString("en-GB",{day:"numeric",month:"short",year:"numeric",timeZone:"UTC"});}
function formatHour(time){const [h,m]=time.split(":").map(Number);return `${h%12||12}:${String(m).padStart(2,"0")} ${h<12?"AM":"PM"}`;}
function loadActivityOptions(){
  // Time options are embedded in HTML, so they are available even before API responds.
  const repeat=byId("activityRepeat");
  repeat.addEventListener("change",()=>byId("repeatUntilWrap").classList.toggle("hidden",repeat.value!=="weekly"));
}
function initManagerCalendar(){
  const input=byId("activityDate"), button=byId("managerCalendarButton"), panel=byId("managerCalendar");
  const today=new Date();
  let visibleYear=2026, visibleMonth=10;
  function choose(y,m,d){input.value=`${y}-${String(m+1).padStart(2,"0")}-${String(d).padStart(2,"0")}`;panel.hidden=true;button.setAttribute("aria-expanded","false");input.dispatchEvent(new Event("change"));}
  function redraw(){
    const mondayStart=(new Date(Date.UTC(visibleYear,visibleMonth,1)).getUTCDay()+6)%7;
    const days=new Date(Date.UTC(visibleYear,visibleMonth+1,0)).getUTCDate();
    const months=["January","February","March","April","May","June","July","August","September","October","November","December"];
    panel.innerHTML=`<div class="manager-cal-header"><button type="button" data-step="-1" aria-label="Previous month">‹</button><strong>${months[visibleMonth]} ${visibleYear} AD</strong><button type="button" data-step="1" aria-label="Next month">›</button></div><div class="manager-cal-days">${["Mon","Tue","Wed","Thu","Fri","Sat","Sun"].map(x=>`<span>${x}</span>`).join("")}${Array.from({length:mondayStart},()=>`<span></span>`).join("")}${Array.from({length:days},(_,i)=>`<button type="button" data-day="${i+1}">${i+1}</button>`).join("")}</div>`;
    panel.querySelectorAll("[data-step]").forEach(b=>b.addEventListener("click",()=>{visibleMonth+=Number(b.dataset.step);if(visibleMonth<0){visibleMonth=11;visibleYear--}if(visibleMonth>11){visibleMonth=0;visibleYear++}redraw()}));
    panel.querySelectorAll("[data-day]").forEach(b=>b.addEventListener("click",()=>choose(visibleYear,visibleMonth,Number(b.dataset.day))));
  }
  button.addEventListener("click",()=>{
    if(panel.hidden){const value=/^\d{4}-\d{2}-\d{2}$/.test(input.value)?input.value:`${today.getFullYear()}-${String(today.getMonth()+1).padStart(2,"0")}-01`;
       visibleYear=Number(value.slice(0,4));visibleMonth=Number(value.slice(5,7))-1;redraw();panel.hidden=false;button.setAttribute("aria-expanded","true");}
    else{panel.hidden=true;button.setAttribute("aria-expanded","false");}
  });
  document.addEventListener("click",e=>{if(!e.target.closest(".manager-date-wrap")){panel.hidden=true;button.setAttribute("aria-expanded","false");}});
  input.addEventListener("change",()=>{if(!/^\d{4}-\d{2}-\d{2}$/.test(input.value))return;const [y,m,d]=input.value.split("-").map(Number);if(new Date(Date.UTC(y,m-1,d)).toISOString().slice(0,10)!==input.value)input.setCustomValidity("Enter a real AD calendar date");else input.setCustomValidity("");});
}
async function loadActivities(){
 try{
  const response=await fetch(`${API_BASE}/activities?mode=${encodeURIComponent(activeMode)}`);
  if(!response.ok)throw new Error(`Could not load activities (HTTP ${response.status})`);
  const data=await response.json();activeRecords=data.activities||[];
  renderActivityList();
 }catch(e){byId("activityList").textContent="Manager notes API not connected. Start the app and check /health.";activeRecords=[];}
}
function renderActivityList(){
 const el=byId("activityList");
 if(!activeRecords.length){el.innerHTML='<p class="empty-activities">No saved activities in this data mode.</p>';return;}
 el.innerHTML=activeRecords.slice(0,30).map(r=>`<div class="activity-record">
 <div><strong>${escapeHtml(r.category)}</strong><span>${escapeHtml(formatGregorianDay(r.day))} · ${escapeHtml(formatHour(r.start_time))}–${escapeHtml(formatHour(r.end_time))}</span>${r.notes?`<p>${escapeHtml(r.notes)}</p>`:""}</div>
 <button type="button" data-remove="${r.id}" aria-label="Delete activity ${r.id}" title="Delete note">Remove</button>
 </div>`).join("");
 el.querySelectorAll("[data-remove]").forEach(button=>button.addEventListener("click",async()=>{
  if(!confirm("Delete this activity note?"))return;
  const response=await fetch(`${API_BASE}/activities/${button.dataset.remove}/remove`,{method:"POST"});
  if(!response.ok){byId("activityStatus").textContent=`Could not delete the record (HTTP ${response.status}).`;return;}
  await loadActivities();if(lastForecastData)renderData(lastForecastData);
 }));
}
byId("activityForm").addEventListener("submit",async event=>{
 event.preventDefault();
 const date=byId("activityDate").value.trim();
 const until=byId("activityRepeatUntil").value.trim();
 if(!/^\d{4}-\d{2}-\d{2}$/.test(date) || (byId("activityRepeat").value==="weekly" && !/^\d{4}-\d{2}-\d{2}$/.test(until))){byId("activityStatus").textContent="Enter dates as YYYY-MM-DD (AD).";return;}
 const payload={data_mode:activeMode,category:byId("activityCategory").value,date,
    start_time:byId("activityStart").value,end_time:byId("activityEnd").value,notes:byId("activityNotes").value,
    repeat:byId("activityRepeat").value,repeat_until:byId("activityRepeat").value==="weekly"?until:null};
 if(payload.start_time>=payload.end_time){byId("activityStatus").textContent="End time must be later than start time.";return;}
 try{
  const response=await fetch(`${API_BASE}/activities`,{method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify(payload)});
  const data=await response.json();if(!response.ok){
    if(response.status===404)throw new Error("Manager notes API not found. Start the app (see README).");
    throw new Error(typeof data.detail==="string"?data.detail:"Please check the activity details.");
  }
  byId("activityStatus").textContent=`Saved ${data.created} activity ${data.created===1?"entry":"entries"}.`;
  byId("activityNotes").value="";
  await loadActivities();if(lastForecastData)renderData(lastForecastData);
 }catch(e){byId("activityStatus").textContent=`Could not save: ${e.message}`;}
});
loadActivityOptions();
initManagerCalendar();
loadActivities();
