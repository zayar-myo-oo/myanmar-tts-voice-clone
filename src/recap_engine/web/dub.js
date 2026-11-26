// Dubbing page: English short -> Burmese voice + Burmese phrase-pop captions (English burned-in text removed locally).
// Uses the helpers of index.html ($, $$, api, J, esc, toast, LS, S, prefs).
const DUB = {file: null, o: null, voices: null};  // o is loaded on first open (index.html defines LS after this file)
const dubInit = () => { if (!DUB.o) DUB.o = {voice: "bc:builtin-aung", vox_model: "lite", remove: "auto", highlight: true, intro: false, review: true, tone: "normal", bed: "keep", ...LS.get("dubOpts", {})}; };
const dsv = () => LS.set("dubOpts", DUB.o);
const DUB_REMOVE = [["auto", "Auto"], ["inpaint", "Inpaint"], ["blur", "Blur"], ["none", "မဖျောက်"]];
const DUB_STAGE = {audio: "အသံခွဲ", transcribe: "English စာသား", captions: "စာတန်း ရှာ", translate: "ဘာသာပြန်", voice: "မြန်မာအသံ", render: "Render"};
const dubState = j => ({done: "✓ ပြီးပြီ", failed: "✕ မအောင်မြင်", cancelled: "■ ရပ်ထား", review: "✎ စစ်ရန် စောင့်နေ", running: "⏳ " + (DUB_STAGE[j.stage] || ""), queued: "… တန်းစီ", new: ""}[j.state] || j.state);

async function dubVoices() { if (!DUB.voices) DUB.voices = await api("/api/dub/voices").catch(() => []); return DUB.voices; }
function dubOptsHtml(o, vs) {
  return `<div class="lbl" style="margin-top:0">မြန်မာ အသံ</div>
  <select class="in" id="dVoice">${vs.map(v => `<option value="${esc(v.id)}" ${o.voice === v.id ? "selected" : ""}>${esc(v.name)} — ${esc(v.engine)}</option>`).join("")}</select>
  <div id="dVoxRow"><div class="lbl">Burma Cat အရည်အသွေး</div><div class="seg" id="dVox">${[["lite", "Lite (မြန်)"], ["pro", "Pro (ပိုကောင်း၊ ၃ ဆ ကြာ)"]].map(([k, n]) => `<button data-k="${k}" class="${o.vox_model === k ? "on" : ""}">${n}</button>`).join("")}</div></div>
  <div class="lbl">ပြောပုံ (Tone)</div><div class="seg" id="dTone">${[["normal","ပုံမှန်"],["rude","ရိုင်းရိုင်း 🤬"],["funny","ဟာသ 😂"]].map(([k, n]) => `<button data-k="${k}" class="${(o.tone || "normal") === k ? "on" : ""}">${n}</button>`).join("")}</div>
  <p class="mut" style="margin:6px 0 0;font-size:12px">ဇာတ်လမ်းက အတူတူပဲ၊ ပြောပုံပဲ ပြောင်းတယ်။ ရိုင်းရိုင်း = ဆဲဆိုပြီး ကိုယ့်မှတ်ချက် ထည့်ပြော၊ ဟာသ = ရယ်စရာ အပိုတွေ ထည့်ပြော။ ⚠ ဆဲစကားပါတဲ့ ဗီဒီယိုကို platform တွေက အသက်ကန့်သတ် / ကြော်ငြာပိတ် / ဖြုတ်ချနိုင်ပါတယ်။</p>
  <div class="lbl">ဗီဒီယိုထဲက English စာကို ဖျောက်နည်း</div><div class="seg" id="dRem">${DUB_REMOVE.map(([k, n]) => `<button data-k="${k}" class="${o.remove === k ? "on" : ""}">${n}</button>`).join("")}</div>
  <p class="mut" style="margin:6px 0 0;font-size:12px">Auto = စာလုံးကိုပဲ ဖျောက် (inpaint)၊ နောက်ခံ ဖြူ/ရှုပ်ရင် စာနောက်လိုက်တဲ့ blur ကို အလိုလို သုံး။ အားလုံး local မှာပဲ လုပ်ပါတယ်။</p>
  <label style="display:flex;gap:8px;align-items:center;margin-top:12px"><input type="checkbox" id="dHi" ${o.highlight ? "checked" : ""}> အဓိကစကားလုံးကို အဝါရောင် highlight</label>
  <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="dBed" ${o.bed === "keep" ? "checked" : ""}> မူရင်း တေးသံ / SFX ကို ထားမယ်</label>
  <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="dIntro" ${o.intro ? "checked" : ""}> အစမှာ hook intro (၂–၃ စက္ကန့်) ထည့်မယ်</label>
  <label style="display:flex;gap:8px;align-items:center;margin-top:8px"><input type="checkbox" id="dRev" ${o.review !== false ? "checked" : ""}> ဘာသာပြန်ပြီးရင် ရပ်၊ စာကို စစ်ပြီးမှ အသံထုတ်မယ်</label>`;
}
function dubOptsBind(o, save) {
  const vx = () => { const r = $("#dVoxRow"); if (r) r.style.display = o.voice.startsWith("bc:") ? "" : "none"; };
  $("#dVoice").onchange = e => { o.voice = e.target.value; vx(); save(); }; vx();
  $$("#dVox button").forEach(b => b.onclick = () => { o.vox_model = b.dataset.k; $$("#dVox button").forEach(x => x.classList.toggle("on", x === b)); save(); });
  $$("#dRem button").forEach(b => b.onclick = () => { o.remove = b.dataset.k; $$("#dRem button").forEach(x => x.classList.toggle("on", x === b)); save(); });
  $$("#dTone button").forEach(b => b.onclick = () => { o.tone = b.dataset.k; $$("#dTone button").forEach(x => x.classList.toggle("on", x === b)); save(); });
  $("#dHi").onchange = e => { o.highlight = e.target.checked; save(); };
  $("#dBed").onchange = e => { o.bed = e.target.checked ? "keep" : "mute"; save(); };
  $("#dIntro").onchange = e => { o.intro = e.target.checked; save(); };
  $("#dRev").onchange = e => { o.review = e.target.checked; save(); };
}
async function dubLlm() { const E = await api("/api/engine").catch(() => ({})); return E.mode === "cloud" && E.llm ? "or:" + E.llm : (prefs.llm || ""); }

async function Dub(arg) {
  dubInit();
  if (arg) return DubJob(arg);
  const vs = await dubVoices();
  if (!vs.find(v => v.id === DUB.o.voice) && vs[0]) DUB.o.voice = vs[0].id;
  $("#view").innerHTML = `<div class="top"><h1>Dubbing</h1><span class="sub">English short → မြန်မာအသံ + မြန်မာ စာတန်း (English စာကို အလိုလို ဖျောက်)</span></div>
  <div style="display:grid;grid-template-columns:minmax(320px,460px) 1fr;gap:18px;padding:0 26px 26px;align-items:start">
   <div><div class="drop" id="dDrop" style="max-width:none;padding:30px;cursor:pointer"><div style="font-size:30px">🎬</div><b id="dName">ဗီဒီယို ရွေးပါ / ဒီမှာ ချပါ</b><div class="mut" style="margin-top:4px">9:16 short · English စကား + English စာတန်း · ၁၀ မိနစ်အောက်</div><input type="file" id="dFile" accept="video/*,.mkv" hidden></div>
    <div class="card" style="padding:14px;margin-top:12px">${dubOptsHtml(DUB.o, vs)}</div>
    <button class="btn" style="width:100%;margin-top:12px;padding:13px" id="dGo" disabled>🎙️ Dub လုပ်မယ်</button><div id="dMsg" class="mut" style="margin-top:8px"></div>
    <div class="note">⚠ တခြားသူ ဖန်တီးထားတဲ့ ဗီဒီယိုကို dub လုပ်ပြီး ပြန်တင်ရင် platform တွေမှာ copyright / reused content ပြဿနာ ရှိနိုင်ပါတယ်။ ကိုယ်ပိုင် (သို့) သုံးခွင့်ရထားတဲ့ ဗီဒီယိုကိုပဲ သုံးပါ၊ ဒါမှမဟုတ် ကိုယ်ပိုင်ဖန်တီးမှု လုံလောက်အောင် ထည့်ပါ။</div></div>
   <div><div class="lbl" style="margin-top:0">မကြာသေးခင်က dub လုပ်ထားတာ</div><div id="dList" class="lib" style="padding:0"></div>
    <div class="lbl">Glossary — ဗီဒီယိုတိုင်းမှာ ဒီအတိုင်း ဘာသာပြန်မယ် (တစ်ကြောင်းကို တစ်ခု: English = မြန်မာ)</div>
    <div class="card" style="padding:12px"><textarea class="in" id="dGloss" rows="6" style="resize:vertical;font-size:14px" placeholder="catapult = ကျောက်တုံးပစ်စက်" data-noi18n></textarea>
     <div style="display:flex;gap:8px;align-items:center;margin-top:8px"><button class="btn ghost" id="dGlossSave">Glossary သိမ်း</button><span class="mut" id="dGlossMsg"></span></div></div></div></div>`;
  dubOptsBind(DUB.o, dsv);
  const glossText = g => Object.entries(g).map(([k, v]) => `${k} = ${v}`).join("\n");
  api("/api/dub/glossary").then(g => { const t = $("#dGloss"); if (t) t.value = glossText(g); }).catch(() => {});
  $("#dGlossSave").onclick = async () => {
    const entries = {}; $("#dGloss").value.split("\n").forEach(l => { const i = l.indexOf("="); if (i > 0) entries[l.slice(0, i).trim()] = l.slice(i + 1).trim(); });
    try { const g = await api("/api/dub/glossary", J("PUT", {entries})); $("#dGloss").value = glossText(g); $("#dGlossMsg").textContent = `သိမ်းပြီး (${Object.keys(g).length})`; } catch (e) { toast(e.message); }
  };
  const setF = f => { if (!f) return; DUB.file = f; $("#dName").textContent = f.name; $("#dGo").disabled = false; };
  const d = $("#dDrop"); d.onclick = () => $("#dFile").click(); $("#dFile").onchange = e => setF(e.target.files[0]);
  d.ondragover = e => e.preventDefault(); d.ondrop = e => { e.preventDefault(); setF(e.dataTransfer.files[0]); };
  if (DUB.file) setF(DUB.file);
  $("#dGo").onclick = async () => {
    const fd = new FormData(); fd.append("file", DUB.file); fd.append("title", DUB.file.name.replace(/\.[^.]+$/, ""));
    fd.append("opts", JSON.stringify({...DUB.o, llm: await dubLlm()}));
    $("#dGo").disabled = true; $("#dMsg").textContent = "ဗီဒီယို တင်နေပါတယ်…";
    try { const j = await api("/api/dub", {method: "POST", body: fd}); DUB.file = null; location.hash = "#/dub/" + j.id; }
    catch (e) { $("#dMsg").innerHTML = `<span class="err">${esc(e.message)}</span>`; $("#dGo").disabled = false; }
  };
  const list = async () => {
    const L = await api("/api/dub").catch(() => []); const el = $("#dList"); if (!el) return;
    el.innerHTML = L.map(j => `<div class="card lc" onclick="location.hash='#/dub/${j.id}'"><div class="th" style="background-image:url('${j.thumb ? `/api/dub/${j.id}/file/thumb.jpg?v=${j.seconds || 0}` : ""}')">${j.thumb ? "" : "🎙️"}</div>
     <div style="padding:10px 12px"><b style="display:block;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${esc(j.title)}</b><span class="mut">${esc(dubState(j))}${j.state === "running" ? " · " + Math.round(j.progress * 100) + "%" : ""}</span></div></div>`).join("") || '<p class="mut">မရှိသေးပါ — ဘယ်ဘက်မှာ ဗီဒီယို ရွေးပြီး စလိုက်ပါ။</p>';
    if (L.some(j => j.state === "running" || j.state === "queued")) S.timer = setTimeout(list, 3000);
  }; list();
}

async function DubJob(id) {
  const vs = await dubVoices(); let drawn = "", edits = null;
  $("#view").innerHTML = `<div class="top"><a class="btn line" href="#/dub">←</a><h1 id="jTitle">Dubbing</h1><span class="sub" id="jSub"></span><span style="flex:1"></span><a class="btn ghost" href="#/dub">＋ ဗီဒီယို အသစ်</a></div><div id="jBody" style="padding:0 26px 26px"></div>`;
  const draw = j => {
    $("#jTitle").textContent = j.title || "Dubbing"; $("#jSub").textContent = dubState(j);
    const busy = j.state === "running" || j.state === "queued", pc = Math.round(j.progress * 100);
    const key = busy ? "busy" : j.state + ":" + (j.seconds || 0) + ":" + (j.lines || []).length;
    if (busy && drawn === "busy") { $("#jBar").style.width = pc + "%"; $("#jMsg").textContent = `${j.message || ""} · ${pc}%`; return; }
    if (key === drawn) return; drawn = key;
    const warn = (j.warnings || []).map(w => `<div class="note">⚠ ${esc(w)}</div>`).join("");
    if (busy) { $("#jBody").innerHTML = `<div class="card" style="padding:20px;max-width:640px"><b>Dub လုပ်နေပါတယ်</b><div class="pbar"><b id="jBar" style="width:${pc}%"></b></div><div class="mut" id="jMsg">${esc(j.message || "")} · ${pc}%</div>
      <p class="mut" style="font-size:12px;margin-top:10px">အဆင့်: အသံခွဲ → English စာသား → စာတန်းနေရာ ရှာ → ဘာသာပြန် → မြန်မာအသံ → render။ ၁ မိနစ် ဗီဒီယိုအတွက် ၅–၁၀ မိနစ်လောက် ကြာနိုင်ပါတယ်။</p>
      <button class="btn red" id="jCancel" style="margin-top:8px">■ ရပ်မယ်</button></div>${warn}`; $("#jCancel").onclick = () => api(`/api/dub/${id}/cancel`, {method: "POST"}); return; }
    const o = {...j.opts}; edits = (j.lines || []).map(x => ({id: x.id, my: x.my || "", kw: x.kw || ""}));
    const cap = j.captions || {}, rev = j.state === "review";
    const hooks = (j.hooks || []).filter(Boolean), gl = Object.entries(j.glossary || {});
    $("#jBody").innerHTML = `<div style="display:grid;grid-template-columns:minmax(260px,360px) 1fr;gap:18px;align-items:start">
     <div>${j.final ? `<video controls playsinline src="/api/dub/${id}/file/final.mp4?v=${j.seconds || 0}" style="width:100%;border-radius:16px;background:#000;max-height:74vh"></video>
       <div style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap"><a class="btn" href="/api/dub/${id}/file/final.mp4" download="${esc(j.title)} - Burmese.mp4">⤓ MP4</a><a class="btn ghost" href="/api/dub/${id}/file/final.srt" download="${esc(j.title)}.srt">⤓ SRT</a><span class="mut" style="margin-left:auto;align-self:center">${j.out_duration ? j.out_duration.toFixed(1) + "s" : ""}</span></div>` : rev ? `<div class="card" style="padding:20px"><b>✎ ဘာသာပြန်ပြီးပါပြီ</b><p class="mut" style="margin:8px 0 0">ညာဘက်က မြန်မာစာကို စစ်/ပြင်ပါ၊ hook တစ်ခု ရွေးပါ၊ ပြီးရင် အောက်က ခလုတ်ကို နှိပ်ပါ။ အသံ မထုတ်ရသေးပါ။</p></div>` : `<div class="card" style="padding:20px"><p class="${j.state === "failed" ? "err" : "mut"}">${esc(j.error || j.message || "ဗီဒီယို မထွက်သေးပါ")}</p></div>`}
      ${warn}<p class="mut" style="font-size:12px;margin-top:10px">${cap.found ? `English စာတန်း တွေ့ပါတယ် (frame ${Math.round((cap.share || 0) * 100)}% မှာ) — ${esc(o.remove)} နဲ့ ဖျောက်ထားပါတယ်` : "English စာတန်း မတွေ့ပါ"}</p>
      <div class="card" style="padding:14px;margin-top:12px">${dubOptsHtml(o, vs)}</div>
      <div style="display:flex;gap:8px;margin-top:12px;flex-wrap:wrap"><button class="btn" id="jRe" style="flex:1">${rev ? "🎙️ အသံထုတ်ပြီး ဗီဒီယို ထုတ်မယ်" : "↻ ပြင်ထားတာနဲ့ ပြန်ထုတ်မယ်"}</button><button class="btn line" id="jRetry" title="အစကနေ ပြန်စစ်ပြီး ကျန်တဲ့အဆင့်တွေ ဆက်လုပ်">▶ ဆက်လုပ်</button><button class="btn red" id="jDel">ဖျက်</button><a class="btn line" href="/api/dub/${id}/file/log.txt" target="_blank">Log</a></div></div>
     <div><div class="lbl" style="margin-top:0">စာကြောင်းတွေ — မြန်မာစာကို ပြင်ပြီး "ပြန်ထုတ်မယ်" နှိပ်ပါ (စကားစုကြား space ခြားပါ၊ space တစ်ခုစီက စာတန်း pop တစ်ခုပါ)</div>
      <div class="card" style="padding:12px;margin-bottom:10px"><div class="mut" style="font-size:12px">Hook intro စာကြောင်း</div><input class="in" id="jHook" value="${esc(j.hook || "")}"></div>
      ${gl.length ? `<p class="mut" style="font-size:12px;margin:0 0 10px" data-noi18n>Glossary: ${gl.map(([k, v]) => esc(k) + " = " + esc(v)).join(" · ")}</p>` : ""}
      ${hooks.length > 1 ? `<div class="card" style="padding:12px;margin-bottom:10px"><div class="mut" style="font-size:12px">ပထမစာကြောင်း (hook) ကို ရွေးပါ — နှိပ်ရင် စာကြောင်း ၁ ထဲ ထည့်ပေးမယ်</div>${hooks.map((h, k) => `<button class="btn line" data-hook="${k}" style="display:block;width:100%;text-align:left;white-space:normal;margin-top:6px;font-weight:500" data-noi18n>${esc(h)}</button>`).join("")}</div>` : ""}
      ${(j.lines || []).map((x, i) => `<div class="card" style="padding:12px;margin-bottom:10px"><div class="mut" style="font-size:12px" data-noi18n>${x.start.toFixed(1)}s · ${esc(x.en)}${x.tts_seconds ? ` · 🔊 ${x.tts_seconds.toFixed(1)}s / ${(x.end - x.start).toFixed(1)}s` : ""}</div>
        <textarea class="in" data-i="${i}" data-f="my" rows="2" style="margin-top:6px;resize:vertical;font-size:15px" data-noi18n>${esc(x.my || "")}</textarea>
        <input class="in" data-i="${i}" data-f="kw" placeholder="အဝါ highlight စကားစု" style="margin-top:6px;font-size:13px" value="${esc(x.kw || "")}" data-noi18n></div>`).join("") || '<p class="mut">ဘာသာပြန် မပြီးသေးပါ။</p>'}</div></div>`;
    dubOptsBind(o, () => {});
    $$("#jBody [data-hook]").forEach(b => b.onclick = () => { const t = $('#jBody textarea[data-i="0"]'); if (!t || !edits[0]) return; t.value = edits[0].my = hooks[+b.dataset.hook];
      $$("#jBody [data-hook]").forEach(x => x.style.borderColor = x === b ? "var(--acc)" : ""); });
    $$("#jBody [data-f]").forEach(el => el.oninput = () => { edits[+el.dataset.i][el.dataset.f] = el.value; });
    $("#jRe").onclick = async () => { try { await api(`/api/dub/${id}`, J("PUT", {lines: edits, hook: $("#jHook").value, opts: o})); drawn = ""; poll(); } catch (e) { toast(e.message); } };
    $("#jRetry").onclick = async () => { await api(`/api/dub/${id}/retry`, {method: "POST"}).catch(e => toast(e.message)); drawn = ""; poll(); };
    $("#jDel").onclick = async () => { if (!confirm("ဒီ dub ကို ဖျက်မလား? (ပြန်ယူလို့ မရပါ)")) return; await api(`/api/dub/${id}`, {method: "DELETE"}).catch(e => toast(e.message)); location.hash = "#/dub"; };
  };
  const poll = async () => {
    clearTimeout(S.timer);
    let j; try { j = await api(`/api/dub/${id}`); } catch (e) { $("#jBody").innerHTML = `<p class="err">${esc(e.message)}</p>`; return; }
    if (!$("#jBody")) return; draw(j);
    if (j.state === "running" || j.state === "queued") S.timer = setTimeout(poll, 1500);
  }; poll();
}
