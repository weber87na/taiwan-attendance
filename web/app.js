/* All user and server content is rendered through textContent or DOM properties. */
"use strict";

const $ = (selector, scope = document) => scope.querySelector(selector);
const state = { user: null, csrf: "", month: taipeiParts().slice(0, 7), view: "dashboard", adminTab: "approvals", renderId: 0 };
const names = {
  roles: { employee: "一般員工", manager: "部門主管", admin: "系統管理員" },
  punches: { in: "上班打卡", out: "下班打卡", break_start: "開始休息", break_end: "結束休息" },
  kinds: { leave: "請假申請", overtime: "加班申請", correction: "補卡申請" },
  statuses: { pending: "待簽核", approved: "已核准", rejected: "已退回", cancelled: "已取消", complete: "完整", incomplete: "未完成", review_required: "待覆核", normal: "正常", invalid: "待確認", absent: "未出勤", missing: "缺少打卡", no_punch: "無打卡", off: "休假", leave: "請假", workday: "工作日" },
  days: { workday: "工作日", weekday: "工作日", rest_day: "休息日", regular_day_off: "例假", holiday: "國定假日", national_holiday: "國定假日" },
  leave: { annual: "特別休假", personal: "事假", sick: "普通傷病假", menstrual: "生理假", marriage: "婚假", bereavement: "喪假", maternity: "產假", paternity: "陪產檢及陪產假", prenatal: "產檢假", family_care: "家庭照顧假", family_care_personal: "照顧家人事假", public: "公假", occupational_injury: "公傷病假" }
};
const pages = {
  dashboard: ["今日總覽", "從每一筆出勤，開始清楚的一天。", "◷", "總覽"],
  records: ["出勤紀錄", "檢視每日工時與打卡紀錄，及早確認異常。", "≡", "紀錄"],
  requests: ["我的申請", "請假、加班與補卡，在這裡追蹤進度。", "↗", "申請"],
  calendar: ["台灣行事曆", "國定假日與週休日，搭配實際排班使用。", "▦", "日曆"],
  calculator: ["薪資與保費試算", "透明呈現計算依據，讓薪資覆核更清楚。", "⊞", "試算"],
  admin: ["團隊管理", "處理簽核、維護排班，掌握團隊出勤。", "⊡", "管理"],
  account: ["帳號設定", "管理個人登入密碼。", "⚙", "帳號"]
};

function el(tag, attrs = {}, children = []) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (value == null || value === false) continue;
    if (key === "class") node.className = value;
    else if (key === "text") node.textContent = String(value);
    else if (key.startsWith("on") && typeof value === "function") node.addEventListener(key.slice(2), value);
    else if (key === "value") node.value = value;
    else if (key === "checked" || key === "disabled" || key === "hidden") node[key] = Boolean(value);
    else node.setAttribute(key, value === true ? "" : String(value));
  }
  for (const child of [].concat(children)) if (child != null) node.append(child instanceof Node ? child : document.createTextNode(String(child)));
  return node;
}
function taipeiParts(date = new Date()) {
  const parts = new Intl.DateTimeFormat("sv-SE", { timeZone: "Asia/Taipei", year: "numeric", month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).formatToParts(date);
  const p = Object.fromEntries(parts.map(x => [x.type, x.value]));
  return `${p.year}-${p.month}-${p.day}T${p.hour}:${p.minute}:${p.second}`;
}
function dateLabel(value, timeOnly = false) {
  if (!value) return "—";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  const options = timeOnly ? { hour: "2-digit", minute: "2-digit", hourCycle: "h23" } : { month: "2-digit", day: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23" };
  return new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", ...options }).format(date);
}
const money = value => new Intl.NumberFormat("zh-TW", { maximumFractionDigits: 2 }).format(Number(value));
const hours = minutes => `${Number((Number(minutes || 0) / 60).toFixed(2))}`;
const localStamp = value => value ? `${value}:00+08:00` : undefined;
const privileged = () => ["manager", "admin"].includes(state.user?.role);
function pill(label, type = "") { return el("span", { class: `pill ${type}`, text: label }); }
function statusPill(status) { return pill(names.statuses[status] || status || "—", status === "approved" || status === "complete" ? "green" : ["pending", "review_required"].includes(status) ? "amber" : status === "rejected" || status === "invalid" ? "red" : "gray"); }
function panel(title, subtitle, children = []) {
  return el("section", { class: "panel" }, [el("div", { class: "panel-header" }, [el("div", {}, [el("h2", { text: title }), subtitle ? el("p", { text: subtitle }) : null])]), ...children]);
}
function empty(message) { return el("div", { class: "empty", text: message }); }
function note(message) { return el("div", { class: "note-box", text: message }); }
function field(label, name, options = {}) {
  const { choices, help, type = "text", ...attrs } = options;
  const input = choices ? el("select", { name, ...attrs }, Object.entries(choices).map(([value, text]) => el("option", { value, text }))) : el(type === "textarea" ? "textarea" : "input", { name, ...(type === "textarea" ? {} : { type }), ...attrs });
  if (options.value != null) input.value = options.value;
  return el("label", {}, [label, input, help ? el("span", { class: "input-help", text: help }) : null]);
}
function formValues(form) { return Object.fromEntries(new FormData(form).entries()); }
function actionButton(text, onclick, cls = "primary") { return el("button", { type: "button", class: `button ${cls}`, text, onclick }); }
function toast(message, error = false) {
  const box = $("#toast");
  box.textContent = message;
  box.className = `toast${error ? " error" : ""}`;
  box.hidden = false;
  clearTimeout(toast.timer);
  toast.timer = setTimeout(() => { box.hidden = true; }, error ? 9000 : 4500);
}
async function api(path, options = {}) {
  const headers = { Accept: "application/json", ...options.headers };
  if (options.body != null) headers["Content-Type"] = "application/json";
  if (options.method && options.method !== "GET") headers["X-CSRF-Token"] = state.csrf;
  let response;
  try { response = await fetch(path, { credentials: "same-origin", ...options, headers, ...(options.body != null ? { body: JSON.stringify(options.body) } : {}) }); }
  catch (_) { throw new Error("無法連線到伺服器，請確認網路連線後再試。"); }
  const data = await response.json().catch(() => ({}));
  if (!response.ok) {
    if (response.status === 401 && state.user) { showLogin(); toast("登入已逾時，請重新登入。", true); }
    const raw = data.error || data.message;
    const error = new Error(typeof raw === "string" ? raw : raw?.message || `要求未完成（${response.status}），請稍後再試。`);
    error.status = response.status;
    throw error;
  }
  return data;
}
async function busy(button, job) {
  if (button.disabled) return;
  button.disabled = true;
  button.setAttribute("aria-busy", "true");
  const before = button.textContent;
  button.textContent = "處理中…";
  try { await job(); }
  catch (error) { toast(error.message || "發生錯誤，請稍後再試。", true); }
  finally { button.disabled = false; button.removeAttribute("aria-busy"); button.textContent = before; }
}
function bindForm(form, submitText, job) {
  const button = el("button", { type: "submit", class: "button primary", text: submitText });
  form.append(el("div", { class: "form-actions" }, [button]));
  form.addEventListener("submit", event => { event.preventDefault(); busy(button, () => job(formValues(form))); });
  return form;
}
function table(headers, rows) {
  if (!rows.length) return empty("這個月份還沒有紀錄。");
  return el("div", { class: "table-wrap" }, [el("table", {}, [el("thead", {}, [el("tr", {}, headers.map(text => el("th", { scope: "col", text })))]), el("tbody", {}, rows.map(row => el("tr", {}, row.map(value => el("td", {}, [value ?? "—"])))) )])]);
}
function ownQuery() { return `month=${encodeURIComponent(state.month)}&user_id=${encodeURIComponent(state.user.id)}`; }
function rowsOf(data) { return Array.isArray(data) ? data : data?.rows || data?.items || []; }
function onlyMine(data) { return rowsOf(data).filter(item => item.user_id == null || String(item.user_id) === String(state.user.id)); }
function showLogin() {
  state.user = null; state.csrf = ""; state.renderId += 1;
  $("#app-view").hidden = true; $("#login-view").hidden = false; $("#boot-loading").hidden = true;
  $("#login-form input[name=password]").value = "";
}
function showApp(data) {
  state.user = data.user; state.csrf = data.csrf_token || "";
  $("#user-name").textContent = state.user.name;
  $("#user-role").textContent = names.roles[state.user.role] || state.user.role;
  $("#user-avatar").textContent = state.user.name?.slice(0, 1) || "人";
  $("#login-view").hidden = true; $("#boot-loading").hidden = true; $("#app-view").hidden = false;
  $("#month-picker").value = state.month;
  $("#nav").replaceChildren(...Object.entries(pages).filter(([key]) => key !== "admin" || privileged()).map(([key, info]) => el("a", { href: `#${key}`, class: "nav-link", "data-page": key, title: info[0] }, [el("span", { class: "nav-icon", "aria-hidden": "true", text: info[2] }), el("span", { class: "nav-text", text: info[3] })])));
  loadView();
}
async function loadView() {
  if (!state.user) return;
  let view = location.hash.replace(/^#/, "") || "dashboard";
  if (!pages[view] || (view === "admin" && !privileged())) view = "dashboard";
  state.view = view;
  const renderId = ++state.renderId;
  $("#page-title").textContent = pages[view][0];
  $("#page-description").textContent = pages[view][1];
  $("#page-eyebrow").textContent = view === "admin" ? "TEAM WORKSPACE" : "MY WORKSPACE";
  $("#month-control").hidden = ["calculator", "account", "requests"].includes(view);
  document.title = `${pages[view][0]}｜勤日`;
  document.querySelectorAll(".nav-link").forEach(link => { const active = link.dataset.page === view; link.classList.toggle("active", active); if (active) link.setAttribute("aria-current", "page"); else link.removeAttribute("aria-current"); });
  $("#view").replaceChildren(el("div", { class: "loading", role: "status", text: "正在讀取資料…" }));
  try {
    const node = await ({ dashboard: renderDashboard, records: renderRecords, requests: renderRequests, calendar: renderCalendar, calculator: renderCalculator, admin: renderAdmin, account: renderAccount }[view])();
    if (renderId === state.renderId && state.user) { $("#view").replaceChildren(node); updateClock(); }
  } catch (error) {
    if (renderId === state.renderId && state.user) $("#view").replaceChildren(el("div", { class: "error-card", role: "alert" }, [el("p", { text: error.message }), actionButton("重新載入", loadView, "soft")]));
  }
}
function updateClock() {
  const clock = $("#live-clock"), date = $("#live-date");
  if (clock) clock.textContent = new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", hour: "2-digit", minute: "2-digit", second: "2-digit", hourCycle: "h23" }).format(new Date());
  if (date) date.textContent = new Intl.DateTimeFormat("zh-TW", { timeZone: "Asia/Taipei", year: "numeric", month: "long", day: "numeric", weekday: "long" }).format(new Date());
}
async function renderDashboard() {
  const [punchData, reportData, requestData] = await Promise.all([api(`/api/punches?${ownQuery()}`), api(`/api/report?${ownQuery()}`), api(`/api/requests?user_id=${state.user.id}`)]);
  const punches = onlyMine(punchData).sort((a, b) => String(b.occurred_at).localeCompare(String(a.occurred_at))), records = onlyMine(reportData), requests = onlyMine(requestData);
  const totalMinutes = records.reduce((sum, row) => sum + Number(row.work_minutes || 0), 0);
  const completedDays = records.filter(row => row.work_minutes != null && row.work_minutes > 0).length;
  const stats = [["本月出勤", completedDays, "天", "已有可計算工時的日期", "▦"], ["已記錄工時", hours(totalMinutes), "小時", "未完成的打卡不計入", "◷"], ["待簽核申請", requests.filter(row => row.status === "pending").length, "筆", "請假、加班與補卡", "↗"], ["本月打卡", punches.length, "筆", "包含休息與核准補卡", "✓"]];
  const cards = el("div", { class: "cards-grid" }, stats.map(([label, value, unit, hint, icon]) => el("div", { class: "stat-card" }, [el("div", { class: "stat-top" }, [label, el("span", { class: "stat-icon", "aria-hidden": "true", text: icon })]), el("span", { class: "stat-number" }, [value, el("small", { text: unit })]), el("p", { class: "stat-note", text: hint })])));
  const clockPanel = panel("今天，也準時開始", "打卡時間以伺服器紀錄為準");
  $(".panel-header", clockPanel).append(pill("Asia / Taipei", "green"));
  clockPanel.append(el("div", { class: "clock-face" }, [el("div", { id: "live-date", class: "clock-date" }), el("div", { id: "live-clock", class: "clock-time", "aria-label": "台灣目前時間" }), el("div", { class: "clock-zone", text: "TAIWAN STANDARD TIME · UTC+8" })]));
  const buttons = el("div", { class: "clock-actions" });
  for (const [kind, label] of Object.entries(names.punches)) buttons.append(actionButton(label, event => busy(event.currentTarget, async () => { await api("/api/clock", { method: "POST", body: { kind } }); toast(`${label}成功`); await loadView(); }), kind === "in" ? "primary" : kind === "out" ? "soft" : "secondary-clock"));
  clockPanel.append(buttons, el("p", { class: "clock-notice", text: "請確實記錄休息起訖；漏打卡可提交補卡申請。" }));
  const recentPanel = panel("最近的打卡", `${state.month} · 依最新時間排序`);
  recentPanel.append(punches.length ? el("ul", { class: "activity-list" }, punches.slice(0, 6).map(item => el("li", { class: "activity-item" }, [el("span", { class: "activity-dot", "aria-hidden": "true" }), el("div", { class: "activity-detail" }, [el("strong", { text: names.punches[item.kind] || item.kind }), el("span", { text: `${taipeiParts(new Date(item.occurred_at)).slice(0, 10)}${item.source === "correction" ? " · 核准補卡" : ""}` })]), el("time", { dateTime: item.occurred_at, text: dateLabel(item.occurred_at, true) })]))) : empty("尚無打卡紀錄，從第一筆上班打卡開始。"));
  const shortcuts = panel("日常捷徑", "需要處理的事，在這裡快速找到", [el("div", { class: "quick-links" }, [["requests", "↗", "新增申請"], ["calendar", "▦", "查看行事曆"], ["records", "≡", "核對出勤"]].map(([href, icon, label]) => el("a", { href: `#${href}`, class: "quick-link" }, [el("span", { "aria-hidden": "true", text: icon }), label])))]);
  return el("div", {}, [cards, el("div", { class: "two-col" }, [el("div", {}, [clockPanel, shortcuts]), el("div", {}, [recentPanel, note("行事曆提供國定假日與預設週休參考。民間企業的補假日期及輪班週期，仍須依勞雇約定與實際排班確認。")])])]);
}
function reportTable(rows, team = false) {
  return table([...(team ? ["員工"] : []), "日期", "日別", "首次上班", "最後下班", "工時", "休息", "核准請假", "核准加班", "狀態／提醒"], rows.map(row => [...(team ? [row.name] : []), row.date, names.days[row.day_type] || row.day_type || "—", dateLabel(row.first_in, true), dateLabel(row.last_out, true), row.work_minutes == null ? "待確認" : `${hours(row.work_minutes)} h`, `${money(row.break_minutes || 0)} 分`, `${row.leave_minutes || 0} 分`, `${row.approved_overtime_minutes || 0} 分`, el("div", {}, [statusPill(row.status), ...(row.issues || []).map(text => el("div", { class: "report-issue", text }))])]));
}
async function renderRecords() {
  const [report, punches] = await Promise.all([api(`/api/report?${ownQuery()}`), api(`/api/punches?${ownQuery()}`)]);
  return el("div", {}, [panel("每日出勤彙整", "時間皆為台灣時間；未完成或異常的打卡不直接認列工時。", [reportTable(onlyMine(report))]), panel("有效打卡紀錄", "核准補卡會保留來源；更正既有打卡時可使用此處編號。", [table(["編號", "時間", "動作", "來源"], onlyMine(punches).sort((a, b) => String(b.occurred_at).localeCompare(String(a.occurred_at))).map(item => [item.id, dateLabel(item.occurred_at), names.punches[item.kind] || item.kind, item.source === "correction" ? pill("核准補卡", "amber") : pill("即時打卡", "gray")]))])]);
}
function requestCard(item, review = false) {
  const card = el("article", { class: "request-card" }, [el("div", { class: "request-top" }, [el("strong", { text: `${review ? `${item.name} · ` : ""}${names.kinds[item.kind] || item.kind}` }), statusPill(item.status)])]);
  const details = [];
  if (item.kind === "correction") details.push(`${names.punches[item.correction_kind] || "補卡"} · ${dateLabel(item.correction_at)}`);
  else details.push(`${dateLabel(item.start_at)} → ${dateLabel(item.end_at)}`, `申請 ${item.requested_minutes || 0} 分鐘${item.leave_type ? ` · ${names.leave[item.leave_type] || item.leave_type}` : ""}`);
  details.push(`提出時間 ${dateLabel(item.created_at)}`);
  for (const text of details) card.append(el("div", { class: "request-meta", text }));
  card.append(el("p", { class: "request-reason", text: item.reason }));
  if (item.review_comment) card.append(el("div", { class: "request-meta", text: `簽核意見：${item.review_comment}` }));
  if (!review && item.status === "pending") card.append(actionButton("取消申請", event => busy(event.currentTarget, async () => { await api(`/api/requests/${encodeURIComponent(item.id)}`, { method: "DELETE", body: {} }); toast("申請已取消。"); await loadView(); }), "ghost small"));
  if (review && item.status === "pending" && String(item.user_id) === String(state.user.id)) card.append(el("p", { class: "request-meta", text: "這是您本人的申請，須由另一位主管簽核。" }));
  if (review && item.status === "pending" && String(item.user_id) !== String(state.user.id)) {
    const comment = el("input", { name: "comment", placeholder: "簽核意見（選填）", "aria-label": `申請 ${item.id} 的簽核意見`, maxLength: 1000 });
    const controls = el("div", { class: "review-controls" }, [comment]);
    for (const [decision, label, cls] of [["approved", "核准", "primary small"], ["rejected", "退回", "danger small"]]) controls.append(actionButton(label, event => busy(event.currentTarget, async () => { await api(`/api/requests/${encodeURIComponent(item.id)}/review`, { method: "POST", body: { decision, comment: comment.value } }); toast(`申請已${label}`); await loadView(); }), cls));
    card.append(controls);
  }
  return card;
}
async function renderRequests() {
  const [requestData, policies] = await Promise.all([api(`/api/requests?user_id=${state.user.id}`), api("/api/policies")]);
  const requests = onlyMine(requestData).sort((a, b) => String(b.created_at).localeCompare(String(a.created_at)));
  const form = el("form");
  const kindField = field("申請類型", "kind", { choices: names.kinds });
  const detail = el("div", { class: "form-grid" });
  function updateFields() {
    const kind = $("select", kindField).value;
    const fields = [];
    if (kind === "leave") {
      const leaveField = field("假別", "leave_type", { choices: names.leave });
      const policyNote = el("details", { class: "leave-policy span-2" });
      const updatePolicy = () => {
        const selected = $("select", leaveField).value, policy = policies.leave_types?.[selected];
        policyNote.replaceChildren(el("summary", { text: `${policy?.label || names.leave[selected]}・適用提醒` }), el("ul", {}, (policy?.notes || ["請依個案法定要件、排班與可用額度，由主管或人資覆核。"]).map(text => el("li", { text }))));
      };
      $("select", leaveField).addEventListener("change", updatePolicy); updatePolicy();
      fields.push(leaveField, policyNote);
    }
    if (kind === "correction") fields.push(field("補卡動作", "correction_kind", { choices: names.punches }), field("補卡時間（台灣時間）", "correction_at", { type: "datetime-local", required: true }), field("更正既有打卡編號（選填）", "target_punch_id", { type: "number", min: 1, step: 1, help: "補上漏打卡請留空；更正時間請填出勤紀錄中的打卡編號。" }));
    else fields.push(field("開始（台灣時間）", "start_at", { type: "datetime-local", required: true }), field("結束（台灣時間）", "end_at", { type: "datetime-local", required: true }), field("申請分鐘數", "requested_minutes", { type: "number", min: 1, step: 1, required: true, placeholder: "例如 480", help: "請排除休息時間；跨日時請依排班計算。" }));
    const reason = field("申請事由", "reason", { type: "textarea", maxLength: 2000, required: true, placeholder: "簡要說明申請原因" });
    reason.classList.add("span-2"); fields.push(reason); detail.replaceChildren(...fields);
  }
  $("select", kindField).addEventListener("change", updateFields);
  form.append(el("div", { class: "stack" }, [kindField, detail]));
  updateFields();
  bindForm(form, "送出申請", async values => {
    const body = { ...values };
    for (const key of ["start_at", "end_at", "correction_at"]) if (body[key]) body[key] = localStamp(body[key]);
    if (body.requested_minutes) body.requested_minutes = Number(body.requested_minutes);
    if (body.target_punch_id) body.target_punch_id = Number(body.target_punch_id);
    else delete body.target_punch_id;
    if (body.start_at && body.end_at && body.end_at <= body.start_at) throw new Error("結束時間必須晚於開始時間。");
    await api("/api/requests", { method: "POST", body }); toast("申請已送出，等待主管簽核。"); await loadView();
  });
  return el("div", { class: "two-col" }, [panel("新增申請", "送出後由主管核對排班與額度。", [form]), panel("我的申請紀錄", "最新的申請會顯示在最上方。", [requests.length ? el("div", { class: "request-list" }, requests.map(item => requestCard(item))) : empty("目前尚無申請紀錄。")])]);
}
async function renderCalendar() {
  const [year, month] = state.month.split("-").map(Number);
  const data = await api(`/api/calendar?year=${year}&month=${month}`);
  const shell = panel(`${year} 年 ${month} 月`, "預設週六休息日、週日例假；不代表所有企業班表。");
  shell.append(el("div", { class: "calendar-top" }, [pill("2026 台灣規則", "gray"), el("div", { class: "legend" }, [el("span", { class: "holiday", text: "國定假日" }), el("span", { text: "週休參考" }), el("span", { class: "workday", text: "待協商補假" })])]));
  const grid = el("div", { class: "calendar-grid", "aria-label": `${year} 年 ${month} 月行事曆` });
  ["日", "一", "二", "三", "四", "五", "六"].forEach(day => grid.append(el("div", { class: "weekday-label", text: day })));
  const start = new Date(Date.UTC(year, month - 1, 1)).getUTCDay();
  for (let i = 0; i < start; i++) grid.append(el("div", { class: "calendar-cell empty-cell", "aria-hidden": "true" }));
  const today = taipeiParts().slice(0, 10);
  for (const day of data.days || []) {
    const kind = day.kind;
    const classes = `calendar-cell${kind === "national_holiday" ? " holiday" : ["rest_day", "regular_day_off"].includes(kind) ? " weekend" : ""}${day.date === today ? " today" : ""}`;
    const cell = el("div", { class: classes, "aria-label": `${day.date} ${day.name || names.days[kind] || ""}${day.proposed_substitute_for ? " 建議補假，待勞雇協商" : ""}` }, [el("time", { class: "day-number", dateTime: day.date, text: String(Number(day.date.slice(-2))) })]);
    if (day.name) cell.append(el("div", { class: "day-name", text: day.name }));
    else if (["rest_day", "regular_day_off"].includes(kind)) cell.append(el("div", { class: "day-name", text: names.days[kind] }));
    if (day.proposed_substitute_for) cell.append(el("div", { class: "day-name", text: "建議補假・待協商" }));
    grid.append(cell);
  }
  for (let i = (start + (data.days || []).length) % 7; i > 0 && i < 7; i++) grid.append(el("div", { class: "calendar-cell empty-cell", "aria-hidden": "true" }));
  shell.append(grid);
  if (data.warnings?.length) shell.append(el("ul", { class: "calendar-notes" }, data.warnings.map(text => el("li", { text }))));
  shell.append(el("p", { class: "calendar-notes", text: "政府機關辦公日曆與民間企業出勤不同；建議補假須經勞雇協商後另行排班。" }));
  return shell;
}
const resultLabels = {
  labor_insurance: "勞保", employment_insurance: "就業保險", occupational_insurance: "職災保險", nhi: "全民健保", pension: "勞工退休金", total: "合計", employee: "員工負擔", employer: "雇主負擔", government: "政府負擔", bases: "投保／提繳級距", rates: "適用費率", dependents: "眷屬人數", reported: "申報眷屬", charged: "計費眷屬", max_charged: "計費上限", hourly_wage: "平日時薪", minutes: "工作／加班分鐘", pay: "應加給金額", monthly_salary: "月薪", amount: "金額", multiplier: "倍率", day_type: "日別", as_of: "試算日期", scope: "適用範圍", labor_insurance_total: "勞保總費率", employment_insurance_total: "就保總費率", nhi_total: "健保總費率", occupational_rate: "職災費率", pension_rate: "退休金提繳率"
};
function resultGroup(data, numericMoney = true) {
  const dl = el("dl", { class: "result-list" });
  for (const [key, value] of Object.entries(data || {})) {
    if (value == null || ["warnings", "sources", "source_urls", "breakdown", "rule_version", "rules_version", "currency", "pay_basis"].includes(key)) continue;
    if (Array.isArray(value)) continue;
    const label = resultLabels[key] || key;
    if (typeof value === "object") dl.append(el("div", {}, [el("div", { class: "result-line" }, [el("dt", { text: label })]), resultGroup(value, key !== "rates" && key !== "dependents")]));
    else dl.append(el("div", { class: "result-line" }, [el("dt", { text: label }), el("dd", { text: typeof value === "number" ? `${money(value)}${numericMoney && !["minutes", "reported", "charged", "max_charged"].includes(key) ? " 元" : ""}` : key === "day_type" ? names.days[value] || value : String(value) })]));
  }
  return dl;
}
function warnings(data) { return data.warnings?.length ? el("ul", { class: "result-warning" }, data.warnings.map(text => el("li", { text }))) : null; }
async function renderCalculator() {
  const overtime = el("form"), overtimeResult = el("div");
  overtime.append(el("div", { class: "form-grid" }, [field("平日每小時工資（元）", "hourly_wage", { type: "number", min: "0.01", step: "0.01", placeholder: "例如 150", required: true }), field("日別", "day_type", { choices: { weekday: "平日延長工時", rest_day: "休息日出勤", national_holiday: "國定假日出勤" } }), field("分鐘數", "minutes", { type: "number", min: 0, max: 720, step: 1, required: true, help: "平日填正常 8 小時後的加班分鐘；其他日別填當日總工作分鐘。" })]));
  bindForm(overtime, "計算加班費", async values => {
    const data = await api("/api/calculate/overtime", { method: "POST", body: { hourly_wage: Number(values.hourly_wage), minutes: Number(values.minutes), day_type: values.day_type } });
    overtimeResult.replaceChildren(el("div", { class: "result-box" }, [el("h3", { text: "加班費試算結果" }), el("div", { class: "stat-number" }, [el("small", { text: "NT$" }), money(data.pay)]), el("p", { class: "result-warning", text: "此為月薪原已給付工資以外，應另加給的金額。" }), table(["計算區段", "分鐘", "倍率", "金額"], (data.breakdown || []).map(item => [item.label, item.minutes, item.multiplier, `NT$ ${money(item.pay)}`])), warnings(data)]));
  });
  const insurance = el("form"), insuranceResult = el("div");
  insurance.append(el("div", { class: "form-grid" }, [field("月薪（元）", "monthly_salary", { type: "number", min: 29500, step: 1, required: true, placeholder: "例如 36000" }), field("依附眷屬人數", "dependents", { type: "number", min: 0, max: 99, step: 1, value: 0, required: true }), field("職災保險費率（%）", "occupational_rate", { type: "number", min: 0, max: 100, step: "0.001", required: true, placeholder: "依公司核定費率填寫", help: "請填投保單位適用的費率，例如 0.2 代表 0.2%。" }), field("雇主勞退提繳率（%）", "pension_rate", { type: "number", min: 6, max: 100, step: "0.01", value: 6, required: true }), field("適用日期", "as_of", { type: "date", min: "2026-01-01", max: "2026-12-31", value: taipeiParts().slice(0, 10), required: true })]));
  bindForm(insurance, "計算勞健保與勞退", async values => {
    const data = await api("/api/calculate/insurance", { method: "POST", body: { monthly_salary: Number(values.monthly_salary), dependents: Number(values.dependents), occupational_rate: Number(values.occupational_rate) / 100, pension_rate: Number(values.pension_rate) / 100, as_of: values.as_of } });
    const display = Object.fromEntries(["as_of", "bases", "employee", "employer", "government", "dependents"].filter(key => data[key] != null).map(key => [key, data[key]]));
    insuranceResult.replaceChildren(el("div", { class: "result-box" }, [el("h3", { text: "每月保費與提繳金額" }), resultGroup(display), warnings(data)]));
  });
  return el("div", {}, [note("試算範圍：2026 年、一般本國全時受僱勞工、全月投保及勞退新制。未涵蓋特殊投保身分、補充保費與不足月計費；例假出勤須另依緊急事由與法定程序處理。"), el("div", { class: "two-col calculator-columns" }, [panel("加班費試算", "依日別分段計算，呈現加給金額。", [overtime, overtimeResult]), panel("勞健保與勞退", "依投保級距計算員工、雇主與政府負擔。", [insurance, insuranceResult])])]);
}
async function renderAdmin() {
  const shell = el("div"), tabs = { approvals: "待簽核", schedules: "員工排班", employees: "員工帳號", reports: "團隊報表", audit: "稽核紀錄" };
  shell.append(el("div", { class: "subtabs", role: "group", "aria-label": "管理功能" }, Object.entries(tabs).map(([key, label]) => actionButton(label, () => { state.adminTab = key; loadView(); }, state.adminTab === key ? "soft small" : "ghost small"))));
  const content = await ({ approvals: renderApprovals, schedules: renderSchedules, employees: renderEmployees, reports: renderReports, audit: renderAudit }[state.adminTab] || renderApprovals)();
  shell.append(content); return shell;
}
async function renderApprovals() {
  const items = rowsOf(await api("/api/requests")).filter(item => item.status === "pending").sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
  const selected = new Set(), list = el("div", { class: "request-list" });
  for (const item of items) {
    const card = requestCard(item, true);
    if (item.kind === "correction" && String(item.user_id) !== String(state.user.id)) {
      const check = el("input", { type: "checkbox", value: item.id, onchange: event => { if (event.target.checked) selected.add(item.id); else selected.delete(item.id); } });
      card.prepend(el("label", { class: "batch-check" }, [check, `選取補卡 #${item.id} 進行批次簽核`]));
    }
    list.append(card);
  }
  const batch = el("form");
  batch.append(el("div", { class: "form-grid" }, [field("批次處理結果", "decision", { choices: { approved: "核准補卡", rejected: "退回補卡" } }), field("批次簽核意見（選填）", "comment", { maxLength: 1000 })]));
  bindForm(batch, "處理選取的補卡", async values => {
    if (!selected.size) throw new Error("請先勾選要處理的補卡申請。");
    const people = new Set(items.filter(item => selected.has(item.id)).map(item => String(item.user_id)));
    if (people.size > 1) throw new Error("每次批次簽核只能選取同一位員工的補卡。");
    await api("/api/requests/review-batch", { method: "POST", body: { request_ids: [...selected], ...values } });
    toast("選取的補卡已完成簽核。"); await loadView();
  });
  const hasBatch = items.some(item => item.kind === "correction" && String(item.user_id) !== String(state.user.id));
  return el("div", {}, [panel("待簽核申請", "請核對事由、實際排班及請假分鐘數後再處理。", [items.length ? list : empty("目前沒有待簽核申請。")]), hasBatch ? panel("批次處理補卡", "漏打整段上下班時，請一併選取同一員工的相關補卡，合併驗證時間順序。", [batch]) : null]);
}
async function renderSchedules() {
  const [usersData, schedulesData] = await Promise.all([api("/api/users"), api(`/api/schedules?month=${encodeURIComponent(state.month)}`)]);
  const users = rowsOf(usersData), usersMap = Object.fromEntries(users.map(user => [user.id, user.name]));
  const form = el("form");
  let editingId = null;
  form.append(el("div", { class: "form-grid" }, [field("員工", "user_id", { choices: Object.fromEntries(users.filter(user => user.active !== false && user.active !== 0).map(user => [user.id, `${user.name}（${user.username}）`])), required: true }), field("日期", "date", { type: "date", required: true, value: `${state.month}-01` }), field("日別", "day_type", { choices: { workday: "工作日", rest_day: "休息日", regular_day_off: "例假", holiday: "國定假日" } }), field("假日名稱（選填）", "holiday_name", { maxLength: 80, placeholder: "例如 中秋節補假" }), field("開始時間", "start", { type: "time", value: "09:00", required: true }), field("結束時間", "end", { type: "time", value: "18:00", required: true }), field("休息分鐘", "break_minutes", { type: "number", min: 0, max: 720, step: 1, value: 60, required: true, help: "結束早於開始時間代表跨日班。" })]));
  bindForm(form, "儲存排班", async values => { await api(editingId ? `/api/schedules/${editingId}` : "/api/schedules", { method: editingId ? "PUT" : "POST", body: { ...values, user_id: Number(values.user_id), break_minutes: Number(values.break_minutes) } }); toast("排班已儲存。"); await loadView(); });
  const editor = panel("新增排班", "已有的班次，請從下方清單點選編輯。", [form]);
  $(".form-actions", form).append(actionButton("重設表單", () => { editingId = null; form.reset(); $("h2", editor).textContent = "新增排班"; }, "ghost"));
  const rows = rowsOf(schedulesData).map(item => {
    const controls = el("div", { class: "row-actions" }, [actionButton("編輯", () => {
      editingId = item.id;
      for (const input of form.elements) if (input.name && item[input.name] != null) input.value = item[input.name];
      $("h2", editor).textContent = `編輯排班 #${item.id}`;
      editor.scrollIntoView({ block: "start", behavior: "smooth" });
      $("select", form).focus({ preventScroll: true });
    }, "soft small"), actionButton("刪除", event => busy(event.currentTarget, async () => { await api(`/api/schedules/${item.id}`, { method: "DELETE", body: {} }); toast("排班已刪除。"); await loadView(); }), "danger small")]);
    return [item.name || usersMap[item.user_id] || item.user_id, item.date, names.days[item.day_type] || item.day_type, item.start || item.start_time, item.end || item.end_time, `${item.break_minutes} 分`, item.holiday_name || "—", controls];
  });
  return el("div", {}, [editor, panel("本月排班", `${state.month} · 已有待審或核准請假的班次會限制異動。`, [table(["員工", "日期", "日別", "開始", "結束", "休息", "假日名稱", "操作"], rows)])]);
}
async function renderEmployees() {
  const users = rowsOf(await api("/api/users"));
  const existing = panel("員工帳號", "帳號權限與到職資訊。", [table(["姓名", "帳號", "角色", "到職日", "月薪", "狀態"], users.map(user => [user.name, user.username, names.roles[user.role] || user.role, user.hire_date, user.monthly_salary == null ? "—" : `NT$ ${money(user.monthly_salary)}`, pill(user.active ? "使用中" : "已停用", user.active ? "green" : "gray")]))]);
  if (state.user.role !== "admin") return existing;
  const form = el("form");
  form.append(el("div", { class: "form-grid" }, [field("姓名", "name", { required: true, maxLength: 80 }), field("登入帳號", "username", { required: true, maxLength: 64, autoComplete: "off" }), field("初始密碼", "password", { type: "password", minLength: 12, required: true, autoComplete: "new-password", help: "至少 12 個字元；請員工登入後變更密碼。" }), field("帳號角色", "role", { choices: names.roles }), field("到職日", "hire_date", { type: "date", required: true }), field("月薪（元）", "monthly_salary", { type: "number", min: 0, step: 1, required: true })]));
  bindForm(form, "建立員工帳號", async values => { await api("/api/users", { method: "POST", body: { ...values, monthly_salary: Number(values.monthly_salary) } }); toast("員工帳號已建立。"); await loadView(); });
  return el("div", {}, [existing, panel("建立新帳號", "請依工作職責授予適當權限。", [form])]);
}
async function renderReports() {
  const data = await api(`/api/report?month=${encodeURIComponent(state.month)}`);
  const block = panel("團隊每月出勤報表", "保留原始打卡與核准申請，工時異常請先覆核。", [reportTable(rowsOf(data), true)]);
  $(".panel-header", block).append(actionButton("下載 CSV", event => busy(event.currentTarget, async () => {
    const response = await fetch(`/api/report.csv?month=${encodeURIComponent(state.month)}`, { credentials: "same-origin" });
    if (!response.ok) { if (response.status === 401) showLogin(); throw new Error("無法下載報表，請確認登入狀態與查詢月份。"); }
    const blob = await response.blob(), url = URL.createObjectURL(blob);
    const a = el("a", { href: url, download: `attendance-${state.month}.csv` }); document.body.append(a); a.click(); a.remove(); setTimeout(() => URL.revokeObjectURL(url), 1000);
  }), "soft small"));
  return block;
}
async function renderAudit() {
  const rows = rowsOf(await api("/api/audit"));
  return panel("操作稽核紀錄", "追蹤資料變更的操作者與時間。", [table(["時間", "操作者", "動作", "資料", "詳細內容"], rows.map(row => [dateLabel(row.created_at), row.actor_name || "系統", row.action, `${row.entity_type || ""} ${row.entity_id || ""}`, el("div", { class: "audit-detail", text: typeof row.detail === "string" ? row.detail : JSON.stringify(row.detail || {}, null, 2) })]))]);
}
async function renderAccount() {
  const form = el("form");
  form.append(el("div", { class: "stack" }, [field("目前密碼", "current_password", { type: "password", autoComplete: "current-password", required: true }), field("新密碼", "new_password", { type: "password", autoComplete: "new-password", minLength: 12, required: true, help: "至少 12 個字元，建議使用獨立且不重複的密碼。" }), field("確認新密碼", "confirm_password", { type: "password", autoComplete: "new-password", minLength: 12, required: true })]));
  bindForm(form, "更新密碼", async values => { if (values.new_password !== values.confirm_password) throw new Error("兩次輸入的新密碼不一致。"); await api("/api/password", { method: "POST", body: { current_password: values.current_password, new_password: values.new_password } }); form.reset(); toast("密碼已更新，請使用新密碼重新登入。"); showLogin(); });
  const block = panel("變更登入密碼", "更新後將回到登入畫面。", [el("div", { class: "account-summary" }, [el("span", { class: "avatar", "aria-hidden": "true", text: state.user.name.slice(0, 1) }), el("div", {}, [el("h2", { text: state.user.name }), el("p", { text: `${state.user.username} · ${names.roles[state.user.role] || state.user.role}` })])]), form]);
  block.classList.add("narrow-panel"); return block;
}

$("#login-form").addEventListener("submit", event => {
  event.preventDefault(); const form = event.currentTarget, button = $("button[type=submit]", form), errorBox = $("#login-error"); errorBox.hidden = true;
  busy(button, async () => {
    try { const data = await api("/api/login", { method: "POST", body: formValues(form) }); form.reset(); showApp(data); }
    catch (error) { errorBox.textContent = error.message; errorBox.hidden = false; }
  });
});
$("#logout").addEventListener("click", event => busy(event.currentTarget, async () => { await api("/api/logout", { method: "POST", body: {} }); showLogin(); }));
$("#month-picker").addEventListener("change", event => { if (/^\d{4}-\d{2}$/.test(event.target.value)) { state.month = event.target.value; loadView(); } });
window.addEventListener("hashchange", loadView);
window.addEventListener("unhandledrejection", event => { event.preventDefault(); toast(event.reason?.message || "發生未預期錯誤，請重新載入。", true); });
window.addEventListener("error", () => toast("頁面發生錯誤，請重新整理後再試。", true));
setInterval(updateClock, 1000);
(async function init() { try { const data = await api("/api/me"); if (data.user) showApp(data); else showLogin(); } catch (error) { showLogin(); if (error.status !== 401) toast(error.message, true); } })();
