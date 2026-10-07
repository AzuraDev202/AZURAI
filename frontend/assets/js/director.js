"use strict";
const Director = {
  brief: null, version: 0, working: false, epoch: 0, mode: true, configured: false, titles: [], user: null, filename: null,
  fields: {subject:"Chủ thể", action:"Hành động", scene:"Bối cảnh", composition:"Bố cục",
    shot:"Cỡ cảnh", angle:"Góc máy", lens:"Ống kính", lighting:"Ánh sáng", palette:"Bảng màu",
    mood:"Cảm xúc", style:"Phong cách", details:"Chi tiết", negative:"Chi tiết muốn tránh"},
  request(method, data) { return {method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)}; },
  reset() {
    this.epoch++; this.brief=null; this.version=0; this.mode=true; this.configured=false; this.filename=null; this.titles=[]; this.working=false; this.user=null;
    $("directorMode").checked=true; $("directorPanel").hidden=false;
    $("directorIdea").value=""; $("directorConcepts").replaceChildren();
    $("directorEditor").hidden=true; $("directorMessage").textContent="";
    $("directorFields").replaceChildren(); $("directorTitle").textContent=""; $("directorWarning").textContent="";
    $("directorActions").hidden=true;
    $("prompt").readOnly=true; $("negative").readOnly=true;
    $("imageFeedback").hidden=true; $("feedbackNote").value=""; $("feedbackStatus").textContent="";
    $("profileFields").replaceChildren(); $("profileStatus").textContent="";
  },
  async load() {
    this.reset(); this.user=currentUser?.id;
    const epoch=this.epoch;
    const [config, draft, profile]=await Promise.all([api("/api/director/config"),api("/api/director/draft"),api("/api/profile")]);
    if(epoch!==this.epoch || this.user!==currentUser?.id) return;
    $("directorProvider").textContent=config.message; this.configured=config.configured; this.renderProfile(profile.profile);
    this.version=draft.version;
    if(draft.brief) { this.brief=draft.brief; $("directorIdea").value=draft.brief.idea; this.render(); }
    this.setMode(true);
  },
  setMode(value) {
    value=true; this.mode=true; $("directorMode").checked=value; $("directorPanel").hidden=!value;
    $("prompt").readOnly=value; $("negative").readOnly=value;
    $("prompt").placeholder=value?"Chọn concept để xem prompt đã biên dịch…": "Mô tả hình ảnh bạn muốn tạo…";
    if(value && this.brief) this.preview();
    this.syncBusy();
  },
  read() {
    if(!this.brief) throw Error("Hãy phát triển ý tưởng và chọn một concept.");
    const brief={...this.brief};
    for(const key of Object.keys(this.fields)) brief[key]=$(`brief-${key}`).value;
    brief.aspect=aspect || brief.aspect;
    return brief;
  },
  render() {
    $("directorEditor").hidden=false; $("directorTitle").textContent=this.brief.title;
    const grid=$("directorFields"); grid.replaceChildren();
    for(const [key,label] of Object.entries(this.fields)) {
      const wrap=document.createElement("div"), title=document.createElement("label"), input=document.createElement("textarea");
      title.htmlFor=input.id=`brief-${key}`; title.textContent=label; input.value=this.brief[key];
      input.rows=2; input.maxLength=key==="negative"?1000:300;
      input.addEventListener("input",()=> { clearTimeout(this.timer); this.timer=setTimeout(()=>this.preview(),300); });
      wrap.append(title,input); grid.append(wrap);
    }
    this.syncBusy();
  },
  async preview() {
    if(!this.mode || !this.brief || this.working || busy) return;
    const epoch=this.epoch, revision=++this.previewRevision;
    try {
      const compiled=await api("/api/director/compile",this.request("POST",this.read()));
      if(epoch!==this.epoch || revision!==this.previewRevision || !this.mode || busy) return;
      $("prompt").value=compiled.prompt; $("negative").value=compiled.negative; updatePromptCount();
      $("directorWarning").textContent=compiled.warnings.join(" ");
    } catch(error) { if(epoch===this.epoch) $("directorMessage").textContent=error.message; }
  },
  previewRevision: 0,
  syncBusy() {
    const locked=busy || this.working;
    document.querySelectorAll("#directorPanel input, #directorPanel textarea, #directorPanel button, #directorActions button, #imageFeedback button, #imageFeedback input, #directorMode")
      .forEach(el=>el.disabled=locked);
    $("generate").disabled=locked || !this.configured || !this.brief;
    $("directorDevelop").disabled=locked || !this.configured;
    $("directorMode").disabled=true;
    $("directorActions").hidden=!this.mode || !this.brief;
  },
  async develop() {
    if(busy || this.working) return;
    this.working=true; this.syncBusy();
    const epoch=this.epoch;
    $("directorMessage").textContent="Đang phát triển 3 hướng sáng tạo…";
    try {
      const data=await api("/api/director/concepts",this.request("POST",{idea:$("directorIdea").value,
        aspect:aspect || "square",previous_titles:this.titles}));
      if(epoch!==this.epoch) return;
      $("directorProvider").textContent=data.message;
      const grid=$("directorConcepts"); grid.replaceChildren();
      this.titles=data.concepts.map(brief=>brief.title);
      for(const brief of data.concepts) {
        const card=document.createElement("button"), name=document.createElement("strong"), scene=document.createElement("span"), style=document.createElement("small");
        card.type="button"; card.className="director-concept";
        name.textContent=brief.title; scene.textContent=brief.scene; style.textContent=`${brief.style} · ${brief.mood}`;
        card.append(name,scene,style); card.onclick=()=> {
          this.brief=brief; this.render(); this.preview();
          grid.querySelectorAll("button").forEach(el=>el.setAttribute("aria-pressed",String(el===card)));
          $("directorMessage").textContent="Sửa brief bên dưới, rồi tạo ảnh. Brief sẽ được lưu khi bạn tạo ảnh.";
        };
        card.setAttribute("aria-pressed","false"); grid.append(card);
      }
      $("directorMessage").textContent="Chọn một concept để tiếp tục. Bạn có thể sửa từng chi tiết.";
    } catch(error) { if(epoch===this.epoch) $("directorMessage").textContent=error.message; }
    finally { if(epoch===this.epoch) { this.working=false; this.syncBusy(); } }
  },
  async save() {
    clearTimeout(this.timer); this.previewRevision++;
    const epoch=this.epoch;
    const saved=await api("/api/director/draft",this.request("PUT",{brief:this.read(),version:this.version}));
    if(epoch!==this.epoch) throw Error("Phiên làm việc đã thay đổi.");
    this.version=saved.version; this.brief=saved.brief;
    $("prompt").value=saved.prompt; $("negative").value=saved.negative; updatePromptCount();
    $("directorWarning").textContent=saved.warnings.join(" ");
    $("directorMessage").textContent=`Đã lưu brief · phiên bản ${saved.version}`;
  },
  renderProfile(profile) {
    $("profile-enabled").checked=profile.enabled;
    $("profile-learn_from_feedback").checked=profile.learn_from_feedback;
    const labels={purpose:"Mục tiêu sáng tạo",style:"Phong cách yêu thích",palette:"Bảng màu",lighting:"Ánh sáng",avoid:"Chi tiết muốn tránh"};
    $("profileFields").replaceChildren();
    for(const [key,label] of Object.entries(labels)) {
      const title=document.createElement("label"), input=document.createElement("textarea");
      title.htmlFor=input.id=`profile-${key}`; title.textContent=label; input.rows=2;
      input.maxLength=["purpose","avoid"].includes(key)?500:300; input.value=profile[key];
      $("profileFields").append(title,input);
    }
  },
  showFeedback(filename) {
    this.filename=filename || null; $("imageFeedback").hidden=!this.filename;
    $("feedbackNote").value=""; $("feedbackStatus").textContent="";
  },
  async restoreCreative(creative) {
    if(!creative?.brief || busy || this.working) return;
    this.brief=creative.brief; aspect=this.brief.aspect; applyPreset(); $("directorIdea").value=this.brief.idea;
    this.render(); this.setMode(true);
    $("directorMessage").textContent="Đã mở brief của ảnh. Bản nháp sẽ được cập nhật khi bạn lưu hoặc tạo ảnh.";
  },
};
$("directorMode").onchange=()=>Director.setMode(true);
$("directorIdea").addEventListener("input",()=> {
  Director.brief=null; $("directorEditor").hidden=true; $("directorConcepts").replaceChildren();
  $("prompt").value=""; updatePromptCount(); Director.syncBusy();
});
$("directorDevelop").onclick=()=>Director.develop();
$("directorSave").onclick=async()=> {
  if(busy || Director.working) return;
  Director.working=true; Director.syncBusy();
  try { await Director.save(); } catch(error) { $("directorMessage").textContent=error.message; }
  finally { Director.working=false; Director.syncBusy(); }
};
$("directorReload").onclick=async()=> {
  try { await Director.load(); Director.setMode(true); }
  catch(error) { $("directorMessage").textContent=error.message; }
};
$("directorActions").querySelectorAll("[data-director-action]").forEach(button=> {
  button.onclick=()=> {
    if(busy || Director.working) return;
    const action=button.dataset.directorAction;
    if(action==="variation") { $("seed").value=-1; run("generate"); }
    else if(action==="concept") { $("directorIdea").focus(); Director.develop(); }
    else { $(`brief-${action}`).focus(); $(`brief-${action}`).scrollIntoView({behavior:"smooth",block:"center"}); }
  };
});

$("profileSave").onclick=async()=> {
  const epoch=Director.epoch;
  try {
    const profile={enabled:$("profile-enabled").checked,learn_from_feedback:$("profile-learn_from_feedback").checked};
    for(const key of ["purpose","style","palette","lighting","avoid"]) profile[key]=$(`profile-${key}`).value;
    await api("/api/profile",Director.request("PUT",profile));
    if(epoch===Director.epoch) $("profileStatus").textContent="Đã lưu. Sở thích áp dụng khi đề xuất concept tiếp theo.";
  } catch(error) { if(epoch===Director.epoch) $("profileStatus").textContent=error.message; }
};
$("profileForget").onclick=async()=> {
  const epoch=Director.epoch;
  try { await api("/api/profile/feedback",{method:"DELETE"}); if(epoch===Director.epoch) $("profileStatus").textContent="Đã xóa phản hồi khỏi bộ nhớ cá nhân. Ảnh vẫn được giữ lại."; }
  catch(error) { if(epoch===Director.epoch) $("profileStatus").textContent=error.message; }
};
for(const [id,rating] of [["feedbackLike",1],["feedbackDislike",-1],["feedbackClear",0]]) $(id).onclick=async()=> {
  if(!Director.filename || busy || Director.working) return;
  const epoch=Director.epoch;
  try {
    await api(`/api/library/${encodeURIComponent(Director.filename)}/feedback`,Director.request("PUT",{rating,note:$("feedbackNote").value}));
    if(epoch===Director.epoch) $("feedbackStatus").textContent=rating===0?"Đã bỏ đánh giá.":"Đã ghi nhận. Director sẽ tham khảo khi phát triển concept tiếp theo.";
  } catch(error) { if(epoch===Director.epoch) $("feedbackStatus").textContent=error.message; }
};
