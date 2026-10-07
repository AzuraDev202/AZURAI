"use strict";
let projectList = [], libraryItems = [], editingProject = null, detailItem = null, projectFilter = null;
let promptTemplates = [], pendingPrompt = "";
function clearWorkspace() {
  projectList=[]; libraryItems=[]; detailItem=null; projectFilter=null; editingProject=null; pendingPrompt=""; promptTemplates=[];
  for (const id of ["projectDialog", "imageDialog"]) if ($(id).open) $(id).close();
  $("projectsGrid").replaceChildren(); $("libraryPageGrid").replaceChildren(); $("projectAssetsGrid").replaceChildren();
}
async function loadDashboardStats() {
  try {
    const [library, projects, features] = await Promise.all([api("/api/library"),api("/api/projects"),api("/api/features")]);
    if (!currentUser) return;
    $("statImages").textContent=library.prompts.length;
    $("statProjects").textContent=projects.projects.length;
    $("statFeatures").textContent=features.features.length;
    $("homeStats").hidden=false;
  } catch(error) { $("homeGreeting").textContent=error.message; }
}
const jsonRequest = (method, data) => ({method, headers:{"Content-Type":"application/json"}, body:JSON.stringify(data)});
function textElement(tag, text, className = "") {
  const element = document.createElement(tag); element.textContent = text; element.className = className; return element;
}
function actionButton(label, action) {
  const button = textElement("button", label, "chip"); button.type = "button"; button.onclick = action; return button;
}
function navigate(view) {
  if (!currentUser && view !== "home") { pendingView = view; openAuth(); return; }
  showView(view);
}
document.querySelectorAll("[data-open]").forEach(button => { button.onclick = () => navigate(button.dataset.open); });
$("backFeatures").onclick = () => navigate("features");
$("settingsAccountButton").onclick = () => $("session").click();
const preferenceIds = ["selection", "mode", "precision", "offline", "negative", "width", "height", "steps", "guidance", "seed"];
function preferenceValues() {
  const data = settings();
  for (const id of preferenceIds.filter(id => !["selection", "mode", "precision", "offline"].includes(id)))
    data[id] = id === "negative" ? $(id).value : Number($(id).value);
  return data;
}
function applyPreferences(data) {
  for (const id of preferenceIds) {
    if (data[id] === undefined) continue;
    if (id === "offline") $(id).checked = data[id];
    else if ($(id).tagName !== "SELECT" || [...$(id).options].some(option => option.value === data[id])) $(id).value = data[id];
  }
  aspect = null; updateSize(); updateSettingsSummary();
}
async function restorePreferences() {
  const data = await api("/api/preferences");
  if (!currentUser) return;
  applyPreferences(data.preferences); await refreshDevice();
}
function updateSettingsSummary() {
  $("defaultsSummary").textContent = `${$("width").value} × ${$("height").value} px · ${$("steps").value} bước · CFG ${$("guidance").value}`;
  $("settingsAccount").textContent = `Đăng nhập: ${currentUser?.username || ""} · Dự án và ảnh riêng theo tài khoản. Thư viện dành cho prompt nổi bật.`;
}
$("saveDefaults").onclick = async () => {
  try { await api("/api/preferences", jsonRequest("PUT", preferenceValues())); $("settingsStatus").textContent = "Đã lưu cấu hình mặc định cho tài khoản."; }
  catch (error) { $("settingsStatus").textContent = error.message; }
};
$("resetDefaults").onclick = async () => {
  const defaults = {selection:"Tự động",mode:"Tự động",precision:"Tự động",offline:false,negative:"",width:512,height:512,steps:20,guidance:7,seed:-1};
  try { await api("/api/preferences", jsonRequest("PUT", defaults)); applyPreferences(defaults); await refreshDevice(); updateSettingsSummary(); $("settingsStatus").textContent = "Đã khôi phục mặc định."; }
  catch (error) { $("settingsStatus").textContent = error.message; }
};
async function loadProjects() {
  try {
    const data = await api("/api/projects"); if (!currentUser) return;
    projectList = data.projects;
    if(projectFilter) projectFilter=projectList.find(project=>project.id===projectFilter.id)||null;
    for (const id of ["generationProject", "imageProject"]) {
      const previous = $(id).value;
      fillSelect(id, [{id:"",name:id === "generationProject" ? "Chưa chọn dự án" : "Chọn dự án"}, ...projectList.map(p=>({id:p.id,name:p.name}))], previous);
    }
    $("projectsGrid").replaceChildren();
    if (!projectList.length) $("projectsGrid").append(textElement("div", "Chưa có dự án. Tạo bộ sưu tập đầu tiên của bạn.", "card recent-empty"));
    for (const project of projectList) {
      const card = document.createElement("article"); card.className = "card project-card";
      const art = document.createElement("div"); art.className = "project-cover";
      if (project.images.length) {
        const image = document.createElement("img"); image.src = `/api/assets/${encodeURIComponent(project.images[0])}`;
        image.alt = project.name; image.onerror = () => { image.remove(); art.textContent = "AZURAI"; }; art.append(image);
      } else art.textContent = "AZURAI";
      const content = document.createElement("div"); content.className = "project-content";
      content.append(textElement("h2",project.name), textElement("p",project.description || "Bộ sưu tập sáng tạo", "help"), textElement("p",`${project.images.length} ảnh · ${new Date(project.created*1000).toLocaleDateString("vi-VN")}`,"help"));
      const actions = document.createElement("div"); actions.className = "project-actions";
      actions.append(actionButton("Mở",()=>{projectFilter=project; showView("project-assets");}), actionButton("Sửa",()=>openProject(project)), actionButton("Xóa", async()=>{
        if (!confirm(`Xóa dự án “${project.name}”? File ảnh xuất trên máy vẫn được giữ.`)) return;
        try { await api(`/api/projects/${project.id}`,{method:"DELETE"}); await loadProjects(); }
        catch(error){$("projectsStatus").textContent=error.message;}
      }));
      content.append(actions); card.append(art,content); $("projectsGrid").append(card);
    }
  } catch(error){$("projectsStatus").textContent=error.message;}
}
function openProject(project=null) {
  editingProject=project; $("projectDialogTitle").textContent=project?"Sửa dự án":"Tạo dự án";
  $("projectName").value=project?.name||""; $("projectDescription").value=project?.description||"";
  $("projectError").textContent=""; $("projectDialog").showModal();
}
$("newProject").onclick=()=>openProject();
function beginFeatureProject(feature) {
  if(!feature.supported) return;
  $("newProjectFeature").textContent=feature.name;
  $("featureProjectForm").reset();
  $("featureProjectError").textContent="";
  pendingPrompt="";
  showView("new-project");
  $("featureProjectName").focus();
}
$("cancelFeatureProject").onclick=()=>navigate("features");
$("featureProjectForm").onsubmit=async(event)=>{
  event.preventDefault();
  if(busy || Director.working) { $("featureProjectError").textContent="Hãy chờ tác vụ hiện tại hoàn tất trước khi tạo dự án mới."; return; }
  $("createFeatureProject").disabled=true;
  $("featureProjectError").textContent="";
  try {
    const name=$("featureProjectName").value.trim();
    if(!name) throw Error("Hãy nhập tên dự án.");
    const project=await api("/api/projects",jsonRequest("POST",{name,description:$("featureProjectDescription").value.trim()}));
    await loadProjects();
    if(!currentUser) return;
    $("generationProject").value=project.id;
    $("directorIdea").value=pendingPrompt;
    $("directorIdea").dispatchEvent(new Event("input"));
    $("prompt").value=""; updatePromptCount();
    showView("create");
    $("directorIdea").focus();
  }catch(error){$("featureProjectError").textContent=error.message;}
  finally{$("createFeatureProject").disabled=false;}
};
$("projectForm").onsubmit=async(event)=>{
  event.preventDefault(); $("saveProject").disabled=true;
  try {
    await api(editingProject?`/api/projects/${editingProject.id}`:"/api/projects",jsonRequest(editingProject?"PUT":"POST",{name:$("projectName").value,description:$("projectDescription").value}));
    $("projectDialog").close(); await loadProjects();
  }catch(error){$("projectError").textContent=error.message;}
  finally{$("saveProject").disabled=false;}
};
async function loadLibraryPage() {
  $("libraryCount").textContent="Đang tải thư viện…";
  try {const data=await api("/api/library"); if(!currentUser)return; promptTemplates=data.prompts; renderPromptLibrary();}
  catch(error){$("libraryCount").textContent=error.message;}
}
function usePromptTemplate(item){
  if(item.feature!=="text-to-image")return;
  beginFeatureProject({name:"Text to Image",supported:true});
  pendingPrompt=item.prompt;
  $("featureProjectName").value=item.title;
  $("featureProjectDescription").value=item.prompt;
}
function promptCard(item){
  const card=document.createElement("article");card.className="card prompt-card";
  card.append(textElement("span",item.feature==="text-to-image"?"Text to Image":"Text to Video","eyebrow"),textElement("h2",item.title),textElement("p",item.prompt,"prompt-copy"));
  const actions=document.createElement("div");actions.className="project-actions";
  const status=textElement("p","","help");status.setAttribute("role","status");
  actions.append(actionButton("Sao chép",async()=>{
    try{await navigator.clipboard.writeText(item.prompt);status.textContent="Đã sao chép prompt.";}
    catch{status.textContent="Không thể truy cập clipboard. Chọn phần prompt và sao chép thủ công.";}
  }));
  const use=actionButton("Dùng prompt",()=>usePromptTemplate(item));use.disabled=item.feature!=="text-to-image";
  if(use.disabled)use.title="Tính năng tạo video chưa được hỗ trợ.";
  actions.append(use);card.append(actions,status);return card;
}
function renderPromptLibrary(){
  const normalize=s=>s.toLowerCase().normalize("NFD").replace(/[\u0300-\u036f]/g,"").replace(/đ/g,"d");
  const query=normalize($("librarySearch").value.trim()),feature=$("libraryFeature").value;
  const items=promptTemplates.filter(item=>(feature==="all"||item.feature===feature)&&normalize(`${item.title} ${item.prompt}`).includes(query));
  $("libraryCount").textContent=`${items.length} prompt`;
  $("libraryPageGrid").replaceChildren(...items.map(promptCard));
  if(!items.length)$("libraryPageGrid").append(textElement("div","Không tìm thấy prompt phù hợp. Thử chủ đề hoặc tính năng khác.","card recent-empty"));
}
async function loadProjectAssets(){
  try{const data=await api("/api/assets");if(!currentUser)return;libraryItems=data.images;renderLibrary();}
  catch(error){$("projectAssetsCount").textContent=error.message;}
}
function renderLibrary() {
  const items=libraryItems.filter(item=>!projectFilter||projectFilter.images.includes(item.filename));
  $("projectAssetsCount").textContent=`${items.length} ảnh${projectFilter?" · "+projectFilter.name:""}`;
  $("projectAssetsGrid").replaceChildren();
  if(!items.length) $("projectAssetsGrid").append(textElement("div","Dự án chưa có ảnh. Tạo ảnh trong Studio và chọn dự án để lưu.","card recent-empty"));
  for(const item of items){
    const button=document.createElement("button"); button.className="library-item";
    const image=document.createElement("img"); image.loading="lazy"; image.src=`/api/assets/${encodeURIComponent(item.filename)}`; image.alt=item.prompt||item.filename;
    button.append(image,textElement("span",item.prompt||item.filename)); button.onclick=()=>openImageDetails(item); $("projectAssetsGrid").append(button);
  }
}
$("librarySearch").oninput=renderPromptLibrary; $("libraryFeature").onchange=renderPromptLibrary;
$("backProjects").onclick=()=>navigate("projects");
$("reloadLibrary").onclick=()=>{projectFilter=null;loadLibraryPage();};
async function openImageDetails(item){
  detailItem=item; $("detailImage").src=`/api/assets/${encodeURIComponent(item.filename)}`;
  $("detailPrompt").textContent=item.prompt||"Không có mô tả.";
  $("detailMeta").textContent=`${item.filename} · ${item.width||"?"} × ${item.height||"?"} px`;
  $("detailDownload").href=$("detailImage").src; $("detailDownload").download=item.filename;
  $("detailStatus").textContent=""; $("imageDialog").showModal(); await loadProjects();
  $("removeImageProject").hidden=!projectFilter;
}
$("reuseImage").onclick=()=>{
  if(!detailItem)return; $("imageDialog").close(); showLibraryImage(detailItem);
  Director.setMode(true);
  if (detailItem.creative) Director.restoreCreative(detailItem.creative);
  else { $("directorIdea").value=detailItem.prompt||""; $("directorIdea").dispatchEvent(new Event("input")); }
  $("prompt").value=detailItem.prompt||""; updatePromptCount();
  for(const [id,value] of Object.entries(detailItem.parameters||{})) if(preferenceIds.includes(id)) $(id).value=value;
  aspect=null;updateSize(); $("prompt").focus();
};
$("addImageProject").onclick=async()=>{
  if(!$("imageProject").value){$("detailStatus").textContent="Chọn hoặc tạo dự án trước khi thêm ảnh.";return;}
  try{await api(`/api/projects/${$("imageProject").value}/images`,jsonRequest("POST",{filename:detailItem.filename}));$("detailStatus").textContent="Đã thêm ảnh vào dự án.";await loadProjects();}
  catch(error){$("detailStatus").textContent=error.message;}
};
$("removeImageProject").onclick=async()=>{
  if(!projectFilter||!detailItem)return;
  try{
    await api(`/api/projects/${projectFilter.id}/images/${encodeURIComponent(detailItem.filename)}`,{method:"DELETE"});
    $("imageDialog").close(); await loadProjects(); renderLibrary();
  }catch(error){$("detailStatus").textContent=error.message;}
};
