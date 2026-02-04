function $(id){ return document.getElementById(id); }

function loadConfig(){
  const api = localStorage.getItem("ADMIN_API_URL") || "http://127.0.0.1:5001";
  const token = localStorage.getItem("ADMIN_TOKEN") || "";
  $("apiUrl").value = api;
  $("adminToken").value = token;
  $("cfgHint").textContent = token ? "Config loaded." : "Set token to access admin endpoints.";
}
function saveConfig(){
  localStorage.setItem("ADMIN_API_URL", $("apiUrl").value.trim());
  localStorage.setItem("ADMIN_TOKEN", $("adminToken").value.trim());
  $("cfgHint").textContent = "Saved.";
}

function apiBase(){ return (localStorage.getItem("ADMIN_API_URL") || "http://127.0.0.1:5001").replace(/\/+$/,""); }
function adminToken(){ return localStorage.getItem("ADMIN_TOKEN") || ""; }

async function apiGet(path){
  const res = await fetch(`${apiBase()}${path}`, {
    headers: { "X-Admin-Token": adminToken() }
  });
  if(!res.ok){
    const t = await res.text();
    throw new Error(`${res.status} ${t}`);
  }
  return res.json();
}

function setPage(title, sub){
  $("pageTitle").textContent = title;
  $("pageSub").textContent = sub;
}

function setView(view){
  document.querySelectorAll(".view").forEach(v=>v.classList.remove("active"));
  const target = document.querySelector(`#view-${view}`);
  if(target) target.classList.add("active");

  document.querySelectorAll(".nav-btn").forEach(b=>b.classList.remove("active"));
  const navBtn = document.querySelector(`.nav-btn[data-view="${view}"]`);
  if(navBtn) navBtn.classList.add("active");

  if(view==="overview"){ setPage("Overview","System summary & latest activity."); }
  if(view==="sessions"){ setPage("Sessions","Browse tracked sessions across users."); }
  if(view==="logs"){ setPage("Logs","Review stored logs across users."); }
  if(view==="crashes"){ setPage("Crashes","Search, filter, group & export crash events."); }
  if(view==="visuals"){ setPage("Visualizations","Charts & trends for sessions and crashes."); }
}

function escapeHtml(s){
  return String(s ?? "")
    .replaceAll("&","&amp;").replaceAll("<","&lt;")
    .replaceAll(">","&gt;").replaceAll('"',"&quot;").replaceAll("'","&#039;");
}

function downloadCSV(filename, rows){
  const csv = rows.map(r => r.map(v => `"${String(v ?? "").replaceAll('"','""')}"`).join(",")).join("\n");
  const blob = new Blob([csv], {type:"text/csv;charset=utf-8;"});
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}

function tableHtml(headers, rows){
  const th = headers.map(h=>`<th>${escapeHtml(h)}</th>`).join("");
  const tr = rows.map(r=>`<tr>${r.map(c=>`<td>${escapeHtml(c)}</td>`).join("")}</tr>`).join("");
  return `<div class="table-scroll"><table class="table"><thead><tr>${th}</tr></thead><tbody>${tr}</tbody></table></div>`;
}

async function loadUsers(){
  const users = await apiGet("/admin/users");
  const sel = $("userFilter");
  sel.innerHTML = `<option value="">All Users</option>`;
  users.forEach(u=>{
    const opt = document.createElement("option");
    opt.value = u;
    opt.textContent = u;
    sel.appendChild(opt);
  });
}

/* -------------------------
   OVERVIEW / SESSIONS / LOGS / CRASHES (your existing behavior)
-------------------------- */
async function renderOverview(){
  const data = await apiGet("/admin/overview");

  const wrap = $("view-overview");
  wrap.innerHTML = `
    <div class="kpi-grid">
      <div class="card kpi">
        <div class="kpi-title">Total Users</div>
        <div class="kpi-value">${data.users_count}</div>
      </div>
      <div class="card kpi">
        <div class="kpi-title">Sessions (Last 7 days)</div>
        <div class="kpi-value">${data.sessions_7d}</div>
      </div>
      <div class="card kpi">
        <div class="kpi-title">Crashes (Last 7 days)</div>
        <div class="kpi-value">${data.crashes_7d}</div>
      </div>
    </div>

    <div class="table-wrap">
      <div class="table-title">Latest Sessions</div>
      ${tableHtml(
        ["User","Start","End","Duration"],
        (data.latest_sessions || []).map(s => [s.user_id, s.session_start, s.session_end, s.total_duration])
      )}
    </div>

    <div class="table-wrap">
      <div class="table-title">Latest Crashes</div>
      ${tableHtml(
        ["Crash ID","User","Time","Exception","Module","Event"],
        (data.latest_crashes || []).map(c => [c.crash_id, c.user_id, c.crash_time, c.exception_code, c.faulting_module, c.event_id])
      )}
    </div>
  `;
}

async function renderSessions(){
  const user = $("userFilter").value.trim();
  const q = user ? `?user=${encodeURIComponent(user)}` : "";
  const rows = await apiGet(`/admin/sessions${q}`);

  const wrap = $("view-sessions");
  wrap.innerHTML = `
    <div class="card">
      <div class="section-title">Sessions Table</div>
      <div class="muted" style="margin-top:6px;">Tip: filter by user using the top-right dropdown.</div>

      <div class="table-wrap">
        ${tableHtml(
          ["Session ID","User","Start","End","Duration"],
          rows.map(s => [s.session_id, s.user_id, s.session_start, s.session_end, s.total_duration])
        )}
      </div>

      <div style="margin-top:12px;">
        <button class="btn" id="exportSessions">Export CSV</button>
      </div>
    </div>
  `;

  $("exportSessions").onclick = () => {
    const csvRows = [
      ["session_id","user_id","session_start","session_end","total_duration"],
      ...rows.map(s => [s.session_id, s.user_id, s.session_start, s.session_end, s.total_duration])
    ];
    downloadCSV("admin_sessions.csv", csvRows);
  };
}

async function renderLogs(){
  const user = $("userFilter").value.trim();
  const q = user ? `?user=${encodeURIComponent(user)}` : "";
  const rows = await apiGet(`/admin/logs${q}`);

  const wrap = $("view-logs");
  wrap.innerHTML = `
    <div class="card">
      <div class="section-title">Logs</div>
      <div class="muted" style="margin-top:6px;">Click a row to view full log details.</div>

      <div class="table-wrap">
        ${tableHtml(
          ["Log ID","User","Timestamp","Preview"],
          rows.map(l => [l.log_id, l.user_id, l.log_timestamp, String(l.log_content||"").slice(0,80)])
        )}
      </div>

      <div style="margin-top:12px;">
        <button class="btn" id="exportLogs">Export CSV</button>
      </div>

      <div class="card" style="margin-top:12px;">
        <div class="section-title">Selected Log</div>
        <pre id="logDetails" class="muted" style="margin-top:10px;">Select a log from the table above.</pre>
      </div>
    </div>
  `;

  const table = wrap.querySelector("table");
  table.querySelectorAll("tbody tr").forEach((tr, idx)=>{
    tr.style.cursor = "pointer";
    tr.onclick = () => {
      $("logDetails").textContent =
        `User: ${rows[idx].user_id}\nTimestamp: ${rows[idx].log_timestamp}\n\n${rows[idx].log_content || ""}`;
    };
  });

  $("exportLogs").onclick = () => {
    const csvRows = [
      ["log_id","user_id","log_timestamp","log_content"],
      ...rows.map(l => [l.log_id, l.user_id, l.log_timestamp, l.log_content])
    ];
    downloadCSV("admin_logs.csv", csvRows);
  };
}

async function renderCrashes(){
  const user = $("userFilter").value.trim();

  const wrap = $("view-crashes");
  wrap.innerHTML = `
    <div class="card">
      <div class="section-title">Crash Monitoring & Analysis</div>
      <div class="muted" style="margin-top:6px;">
        Search + filter crashes, view details, and analyze grouped signatures.
      </div>

      <div class="filter-card card" style="margin-top:12px;">
        <div class="filters">
          <div class="field">
            <label>Search</label>
            <input id="crashQ" class="control" type="text" placeholder="Search message/module/exception..." />
          </div>
          <div class="field">
            <label>Exception code</label>
            <input id="crashExc" class="control" type="text" placeholder="0xc0000409" />
          </div>
          <div class="field">
            <label>Faulting module</label>
            <input id="crashMod" class="control" type="text" placeholder="ucrtbase.dll" />
          </div>
          <div class="field field-actions">
            <label>&nbsp;</label>
            <div style="display:flex; gap:10px; flex-wrap:wrap;">
              <button class="btn primary" id="crashApply">Apply</button>
              <button class="btn" id="crashClear">Clear</button>
            </div>
          </div>
        </div>
      </div>

      <div class="split" style="margin-top:12px;">
        <div class="card">
          <div class="section-title">Crash List</div>
          <div class="muted" style="margin-top:6px;">Select a crash to view full details.</div>
          <div style="height:10px"></div>
          <div id="crashList" class="list"></div>

          <div style="margin-top:12px;">
            <button class="btn" id="exportCrashes">Export Crashes CSV</button>
          </div>
        </div>

        <div class="card">
          <div class="section-title">Top Crash Signatures</div>
          <div class="muted" style="margin-top:6px;">
            Grouped by exception_code + faulting_module + event_id.
          </div>

          <div class="table-wrap">
            <div id="crashSummary"></div>
          </div>

          <div style="margin-top:12px;">
            <button class="btn" id="exportSummary">Export Summary CSV</button>
          </div>

          <div class="card" style="margin-top:12px;">
            <div class="section-title">Selected Crash Details</div>
            <pre id="crashDetails" class="muted" style="margin-top:10px;">Select a crash from the list.</pre>
          </div>
        </div>
      </div>
    </div>
  `;

  async function loadCrashes(){
    const q = $("crashQ").value.trim();
    const exc = $("crashExc").value.trim();
    const mod = $("crashMod").value.trim();

    const params = new URLSearchParams();
    if(user) params.set("user", user);
    if(q) params.set("q", q);
    if(exc) params.set("exception_code", exc);
    if(mod) params.set("faulting_module", mod);

    const list = await apiGet(`/admin/crashes?${params.toString()}`);
    const summary = await apiGet(`/admin/crashes/summary${user ? `?user=${encodeURIComponent(user)}` : ""}`);

    const listDiv = $("crashList");
    listDiv.innerHTML = "";
    if(!list.length){
      listDiv.innerHTML = `<div class="list-item">No crashes found.</div>`;
    }else{
      list.forEach((c)=>{
        const reason = [c.exception_code, c.faulting_module].filter(Boolean).join(" • ") || "Unknown reason";
        const el = document.createElement("div");
        el.className = "list-item";
        el.innerHTML = `<b>ID ${escapeHtml(c.crash_id)}</b> • ${escapeHtml(c.crash_time)}<br><span class="muted">${escapeHtml(reason)}</span>`;
        el.onclick = ()=>{
          listDiv.querySelectorAll(".list-item").forEach(x=>x.classList.remove("active"));
          el.classList.add("active");
          $("crashDetails").textContent =
            `Crash ID: ${c.crash_id}\nUser: ${c.user_id}\nCrash Time: ${c.crash_time}\nSession Start: ${c.session_start}\nSession End: ${c.session_end}\nProvider: ${c.provider}\nEvent ID: ${c.event_id}\nException Code: ${c.exception_code}\nFaulting Module: ${c.faulting_module}\n\nMessage:\n${c.message || ""}`;
        };
        listDiv.appendChild(el);
      });
    }

    $("crashSummary").innerHTML = tableHtml(
      ["Signature","Count","Last Seen","Example"],
      summary.map(s => [s.signature, s.count, s.last_seen, s.example])
    );

    $("exportCrashes").onclick = ()=>{
      const csvRows = [
        ["crash_id","user_id","crash_time","session_start","session_end","provider","event_id","exception_code","faulting_module","message"],
        ...list.map(c => [c.crash_id, c.user_id, c.crash_time, c.session_start, c.session_end, c.provider, c.event_id, c.exception_code, c.faulting_module, c.message])
      ];
      downloadCSV("admin_crashes.csv", csvRows);
    };

    $("exportSummary").onclick = ()=>{
      const csvRows = [
        ["signature","count","last_seen","example"],
        ...summary.map(s => [s.signature, s.count, s.last_seen, s.example])
      ];
      downloadCSV("admin_crash_summary.csv", csvRows);
    };
  }

    let crashTimer;
    ["crashQ","crashExc","crashMod"].forEach(id=>{
    $(id).addEventListener("input", ()=>{
        clearTimeout(crashTimer);
        crashTimer = setTimeout(loadCrashes, 300);
    });
    });

    $("crashClear").onclick = ()=>{
        $("crashQ").value = "";
        $("crashExc").value = "";
        $("crashMod").value = "";
        loadCrashes();
    };

    await loadCrashes();
}

/* -------------------------
   VISUALIZATIONS (NEW)
-------------------------- */

const chartRegistry = new Map(); // key -> Chart instance

function destroyChart(key){
  const c = chartRegistry.get(key);
  if(c){
    c.destroy();
    chartRegistry.delete(key);
  }
}

function setCanvas(id){
  // ensure unique canvas exists
  return document.getElementById(id);
}

function chartCardHTML(id, title, sub){
  return `
    <div class="chart-card">
      <div class="chart-head">
        <div>
          <div class="chart-title">${escapeHtml(title)}</div>
          <div class="chart-sub">${escapeHtml(sub)}</div>
        </div>
      </div>
      <div class="chart-wrap">
        <canvas id="${escapeHtml(id)}"></canvas>
      </div>
    </div>
  `;
}

function getDateISO(d){
  // YYYY-MM-DD
  const pad = (n)=> String(n).padStart(2,"0");
  return `${d.getFullYear()}-${pad(d.getMonth()+1)}-${pad(d.getDate())}`;
}

function getVisualRange(){
  const from = $("fromDate")?.value;
const to = $("toDate")?.value;

  return { from, to };
}

function qsFromTo(){
  const {from,to} = getVisualRange();
  const p = new URLSearchParams();
  if(from) p.set("from", from);
  if(to) p.set("to", to);
  const q = p.toString();
  return q ? `?${q}` : "";
}

async function renderVisuals(){
  const wrap = $("view-visuals");

  // default: last 30 days in input
  const now = new Date();
  const d30 = new Date(now.getTime() - 29*24*3600*1000);

  wrap.innerHTML = `
    <section class="card">
      <div class="section-title">Filters</div>
      <div class="muted" style="margin-top:6px;">Select a date range for charts (default last 30 days).</div>

      <div class="filters" style="grid-template-columns: 1fr 1fr auto; margin-top:12px;">
        <div class="field">
          <label>From (YYYY-MM-DD)</label>
          <input type="date" id="fromDate">
        </div>
        <div class="field">
          <label>To (YYYY-MM-DD)</label>
          <input type="date" id="toDate">
        </div>
        <div class="field field-actions">
          <label>&nbsp;</label>
          <div style="display:flex; gap:10px; flex-wrap:wrap;">
            <button id="vApply" class="btn primary">Apply</button>
            <button id="vReset" class="btn">Reset</button>
          </div>
        </div>
      </div>
    </section>

    <div style="height:14px"></div>

    <section class="card">
      <div class="section-title">Session Visualizations</div>
      <div class="muted" style="margin-top:6px;">Usage trends and engagement patterns.</div>
      <div style="height:12px"></div>
      <div class="chart-grid" id="sessionCharts"></div>
    </section>

    <div style="height:14px"></div>

    <section class="card">
      <div class="section-title">Crash Visualizations</div>
      <div class="muted" style="margin-top:6px;">Crash trends and most frequent causes.</div>
      <div style="height:12px"></div>
      <div class="chart-grid" id="crashCharts"></div>
    </section>
  `;

  // after wrap.innerHTML = `...`
  $("fromDate").value = getDateISO(d30);
  $("toDate").value = getDateISO(now);

  $("vReset").onclick = ()=>{
    $("fromDate").value = getDateISO(d30);
    $("toDate").value = getDateISO(now);
    loadAllCharts();
  };

  // add chart cards
  $("sessionCharts").innerHTML = `
    ${chartCardHTML("ch_sessions_per_user","Total sessions per user","Bar chart: number of sessions by user")}
    ${chartCardHTML("ch_duration_daily","Session duration over time","Line chart: total session hours per day")}
    ${chartCardHTML("ch_activity_hourly","User activity per hour","Bar chart: sessions by hour of day")}
    ${chartCardHTML("ch_daily_users","Daily user trend","Line chart: active users per day")}
    ${chartCardHTML("ch_weekly_users","Weekly user trend","Bar chart: active users per week")}
    ${chartCardHTML("ch_new_vs_returning","New vs Returning users","Pie chart: users first seen in range vs returning")}
  `;

  $("crashCharts").innerHTML = `
    ${chartCardHTML("ch_crashes_daily","Crashes per day","Line chart: crashes by day")}
    ${chartCardHTML("ch_crashes_hourly","Crashes per hour","Bar chart: crashes by hour of day")}
    ${chartCardHTML("ch_crashes_module","Crashes by module","Bar chart: top faulting modules")}
    ${chartCardHTML("ch_crashes_exception","Crashes by exception","Bar chart: top exception codes")}
    ${chartCardHTML("ch_crashes_signatures","Top crash signatures","Bar chart: top grouped crash signatures")}
  `;

  async function loadAllCharts(){
    // destroy old charts (if switching away and back)
    [...chartRegistry.keys()].forEach(k=>destroyChart(k));

    const q = qsFromTo();

    // Sessions
    const sessionsPerUser = await apiGet(`/admin/charts/sessions_per_user${q}`);
    buildBar("sessions_per_user", "ch_sessions_per_user",
      sessionsPerUser.map(r=>r.user_id),
      sessionsPerUser.map(r=>r.sessions)
    );

    const durationDaily = await apiGet(`/admin/charts/session_duration_daily${q}`);
    buildLine("duration_daily", "ch_duration_daily",
      durationDaily.map(r=>r.day),
      durationDaily.map(r=>Number(r.hours || 0))
    );

    const hourly = await apiGet(`/admin/charts/activity_hourly${q}`);
    buildBar("activity_hourly", "ch_activity_hourly",
      hourly.map(r=>String(r.hour).padStart(2,"0")),
      hourly.map(r=>r.sessions)
    );

    const dailyUsers = await apiGet(`/admin/charts/daily_users${q}`);
    buildLine("daily_users", "ch_daily_users",
      dailyUsers.map(r=>r.day),
      dailyUsers.map(r=>r.active_users)
    );

    const weeklyUsers = await apiGet(`/admin/charts/weekly_users${q}`);
    buildBar("weekly_users", "ch_weekly_users",
      weeklyUsers.map(r=>r.week),
      weeklyUsers.map(r=>r.active_users)
    );

    const newVs = await apiGet(`/admin/charts/new_vs_returning${q}`);
    buildPie("new_vs_returning", "ch_new_vs_returning",
      ["New Users","Returning Users"],
      [newVs.new_users || 0, newVs.returning_users || 0]
    );

    // Crashes
    const crashesDaily = await apiGet(`/admin/charts/crashes_daily${q}`);
    buildLine("crashes_daily", "ch_crashes_daily",
      crashesDaily.map(r=>r.day),
      crashesDaily.map(r=>r.crashes)
    );

    const crashesHourly = await apiGet(`/admin/charts/crashes_hourly${q}`);
    buildBar("crashes_hourly", "ch_crashes_hourly",
      crashesHourly.map(r=>String(r.hour).padStart(2,"0")),
      crashesHourly.map(r=>r.crashes)
    );

    const byModule = await apiGet(`/admin/charts/crashes_by_module${q}`);
    buildBar("crashes_by_module", "ch_crashes_module",
      byModule.map(r=>r.module),
      byModule.map(r=>r.crashes)
    );

    const byExc = await apiGet(`/admin/charts/crashes_by_exception${q}`);
    buildBar("crashes_by_exception", "ch_crashes_exception",
      byExc.map(r=>r.exception),
      byExc.map(r=>r.crashes)
    );

    const sigs = await apiGet(`/admin/charts/crashes_top_signatures${q}`);
    buildBar("crashes_signatures", "ch_crashes_signatures",
      sigs.map(r=>r.signature),
      sigs.map(r=>r.crashes)
    );
  }

  $("vApply").onclick = loadAllCharts;
  $("vReset").onclick = ()=>{
    $("vFrom").value = getDateISO(d30);
    $("vTo").value = getDateISO(now);
    loadAllCharts();
  };

  await loadAllCharts();
}

/* -------------------------
   Chart Builders (Chart.js)
-------------------------- */

function buildBar(key, canvasId, labels, values){
  destroyChart(key);
  const ctx = setCanvas(canvasId);
  if(!ctx) return;

  const chart = new Chart(ctx, {
    type: "bar",
    data: {
      labels,
      datasets: [{
        label: "Count",
        data: values
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: { enabled: true }
      },
      scales: {
        x: { ticks: { maxRotation: 0, autoSkip: true } },
        y: { beginAtZero: true }
      }
    }
  });

  chartRegistry.set(key, chart);
}

function buildLine(key, canvasId, labels, values){
  destroyChart(key);
  const ctx = setCanvas(canvasId);
  if(!ctx) return;

  const chart = new Chart(ctx, {
    type: "line",
    data: {
      labels,
      datasets: [{
        label: "Value",
        data: values,
        tension: 0.25,
        fill: false,
        pointRadius: 2
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false }
      },
      scales: {
        y: { beginAtZero: true }
      }
    }
  });

  chartRegistry.set(key, chart);
}

function buildPie(key, canvasId, labels, values){
  destroyChart(key);
  const ctx = setCanvas(canvasId);
  if(!ctx) return;

  const chart = new Chart(ctx, {
    type: "pie",
    data: {
      labels,
      datasets: [{
        data: values
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { position: "bottom" }
      }
    }
  });

  chartRegistry.set(key, chart);
}

/* -------------------------
   Navigation + Boot
-------------------------- */

async function refreshCurrent(){
  const view =
    document.querySelector(".nav-btn.active")?.dataset?.view || "overview";

  toggleUserFilter(view);

  if(view==="overview") return renderOverview();
  if(view==="sessions") return renderSessions();
  if(view==="logs") return renderLogs();
  if(view==="crashes") return renderCrashes();
  if(view==="visuals") return renderVisuals();
}

function toggleUserFilter(view){
  const uf = document.getElementById("userFilter");
  if(!uf) return;

  // Only show for per-user data
  if(view === "sessions" || view === "logs" || view === "crashes"){
    uf.style.display = "inline-block";
  } else {
    uf.style.display = "none";
    uf.value = ""; // reset filter
  }
}

async function boot(){
  try{
    await loadUsers();
    await refreshCurrent();
    $("cfgHint").textContent = "Connected.";
  }catch(e){
    $("cfgHint").textContent = `Error: ${e.message}`;
  }
}

async function main(){
  loadConfig();

  $("saveConfig").onclick = async ()=>{
    saveConfig();
    await boot();
  };

  document.querySelectorAll(".nav-btn").forEach(btn=>{
    btn.onclick = async ()=>{
      setView(btn.dataset.view);
      await refreshCurrent();
    };
  });

  $("refreshBtn").onclick = refreshCurrent;
  $("userFilter").onchange = refreshCurrent;

  await boot();
}

main();
