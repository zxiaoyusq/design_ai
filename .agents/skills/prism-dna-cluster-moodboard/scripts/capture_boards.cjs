// 以真实浏览器保留当前视窗组合和功能证据；截图与程序检查不授予审美通过。
'use strict';
const fs=require('fs');
const path=require('path');
const crypto=require('crypto');
const {pathToFileURL}=require('url');

function args(){
  const values={};
  const input=process.argv.slice(2);
  if(input.includes('--help')||input.length===0){
    console.log('用法：node capture_boards.cjs --delivery DIR --out FRESH_DIR [--board BOARD_ID] [--playwright PATH]\n读取delivery-manifest.json，实际截每张板的#board-grid，并核验桌面/390px窄屏、筛选、原图、ROI及键盘关闭。\n输出capture-manifest.json、每板PNG及逐板SHA/顺序/ROI清单；拒绝覆盖非空输出目录。无模型调用。');process.exit(0);
  }
  for(let i=0;i<input.length;i+=2){if(!input[i].startsWith('--')||!input[i+1])throw Error('参数必须为--名称 值');values[input[i].slice(2)]=input[i+1];}
  if(!values.delivery||!values.out)throw Error('必须提供--delivery和--out');
  return values;
}
const sha=p=>crypto.createHash('sha256').update(fs.readFileSync(p)).digest('hex');
const fileRef=p=>({path:path.resolve(p),sha256:sha(p)});
function write(p,value){fs.writeFileSync(p,JSON.stringify(value,null,2)+'\n',{flag:'wx'});}
// 只记录几何尺寸：倍率以CSS像素/原生像素计，不设清晰度阈值、不参与视觉或功能通过判定。
function readabilityMetrics(natural,roi,displayCssDimensions,devicePixelRatio){
  const native=[natural[0]*roi[2],natural[1]*roi[3]];
  return {original_dimensions_px:natural,roi_native_dimensions_px:native,display_css_dimensions_px:displayCssDimensions,display_scale_css_per_native_pixel:displayCssDimensions.map((value,axis)=>value/native[axis]),device_pixel_ratio:devicePixelRatio,diagnostic_only:true,visual_pass_awarded:false};
}
async function ready(page){await page.waitForFunction(()=>window.__prismReady===true&&[...document.querySelectorAll('.viewport img')].every(image=>image.complete&&image.naturalWidth>0));await page.evaluate(()=>document.fonts.ready);await page.waitForTimeout(120);}
// 最终说明区会改变绝对Y和浏览器栅格化相位；只平移同一grid到固定原点，严格保留其原尺寸和内容。
async function gridLayout(page){
  const result=await page.evaluate(()=>{
    const grid=document.getElementById('board-grid'),bounds=grid.getBoundingClientRect(),style=getComputedStyle(grid);
    const rectangle=node=>{const r=node.getBoundingClientRect();return [r.x-bounds.x,r.y-bounds.y,r.width,r.height];};
    const font=node=>{const s=getComputedStyle(node);return [s.fontFamily,s.fontSize,s.fontWeight,s.lineHeight,s.letterSpacing];};
    return {inline_style:grid.getAttribute('style'),viewport_origin:[bounds.x,bounds.y],document_origin:[bounds.x+scrollX,bounds.y+scrollY],
      geometry:{size:[bounds.width,bounds.height],grid_columns:style.gridTemplateColumns,grid_rows:style.gridTemplateRows,grid_font:font(grid),device_pixel_ratio:devicePixelRatio,
        tiles:[...grid.querySelectorAll('.tile')].map(tile=>({image_id:tile.dataset.imageId,tile:rectangle(tile),window:rectangle(tile.querySelector('.image-window')),image:rectangle(tile.querySelector('img')),caption_font:font(tile.querySelector('.tile-caption'))}))},content:grid.innerHTML};
  });
  result.content_sha256=crypto.createHash('sha256').update(result.content).digest('hex');delete result.content;return result;
}
async function normalizeGridOrigin(page){
  const original=await gridLayout(page);
  await page.evaluate(width=>{Object.assign(document.getElementById('board-grid').style,{position:'fixed',top:'0px',left:'0px',width:width+'px',zIndex:'1000'});},original.geometry.size[0]);
  await ready(page);const normalized=await gridLayout(page);
  return {policy:'same_grid_position_only_fixed_viewport_origin_v1',original_layout:original,capture_layout:normalized,
    content_and_geometry_unchanged:original.content_sha256===normalized.content_sha256&&JSON.stringify(original.geometry)===JSON.stringify(normalized.geometry),original_style_restored:false};
}
async function restoreGridOrigin(page,audit){
  await page.evaluate(style=>{const grid=document.getElementById('board-grid');if(style===null)grid.removeAttribute('style');else grid.setAttribute('style',style);},audit.original_layout.inline_style);
  await ready(page);const restored=await gridLayout(page);
  audit.original_style_restored=restored.inline_style===audit.original_layout.inline_style;
  audit.restored_layout=restored;
  if(!audit.original_style_restored||restored.content_sha256!==audit.original_layout.content_sha256||JSON.stringify(restored.geometry)!==JSON.stringify(audit.original_layout.geometry))throw Error('截图后未恢复原grid内容或布局');
}
async function main(){
  const options=args();const delivery=path.resolve(options.delivery),output=path.resolve(options.out);
  const {chromium}=require(options.playwright||'/tmp/bubble-ui-check/node_modules/playwright');
  if(fs.existsSync(output)&&fs.readdirSync(output).length)throw Error('输出目录非空，请保留旧证据并指定新目录');fs.mkdirSync(output,{recursive:true});
  const manifestPath=path.join(delivery,'delivery-manifest.json'),manifest=JSON.parse(fs.readFileSync(manifestPath,'utf8'));
  const boards=options.board?manifest.boards.filter(board=>board.board_id===options.board):manifest.boards;if(options.board&&!boards.length)throw Error('指定board_id不存在');
  // 先核对交付中的真实原图和HTML，避免误把其他版本截图写入当前证据。
  for(const asset of manifest.assets){if(sha(path.join(delivery,asset.path))!==asset.sha256)throw Error('原图SHA与交付不符：'+asset.path);}
  const browser=await chromium.launch({headless:true,args:['--no-sandbox']});const results=[];const errors=[];
  try{
    for(const board of boards){
      const html=path.join(delivery,board.path);if(sha(html)!==board.html_sha256)throw Error('HTML SHA与交付不符：'+board.board_id);
      const page=await browser.newPage({viewport:{width:1440,height:1080}});const pageErrors=[];page.on('pageerror',error=>pageErrors.push(error.message));const external=[];page.on('request',request=>{if(request.resourceType()==='image'&&/^https?:/i.test(request.url()))external.push(request.url());});
      await page.goto(pathToFileURL(html).href);await ready(page);
      const actualLayoutIdentity=await page.evaluate(()=>JSON.parse(document.getElementById('page-data').textContent).board.layout_identity||null);
      if(actualLayoutIdentity!==(board.layout_identity||null))throw Error('HTML 与 manifest 布局身份不同');
      const grid=page.locator('#board-grid');const png=path.join(output,board.board_id+'.png');
      const normalization=await normalizeGridOrigin(page);let actual;
      try{
        if(!normalization.content_and_geometry_unchanged||JSON.stringify(normalization.capture_layout.viewport_origin)!=='[0,0]')throw Error('标准化只允许位置变化，原grid内容/尺寸/字体/像素尺度必须完全不变');
        await grid.screenshot({path:png});
        actual=await page.evaluate(()=>({members:[...document.querySelectorAll('.tile')].map(tile=>{const img=tile.querySelector('img'),window=tile.querySelector('.image-window'),i=img.getBoundingClientRect(),w=window.getBoundingClientRect();return {image_id:tile.dataset.imageId,original_sha:img.dataset.originalSha,window:[window.clientWidth,window.clientHeight],display_css_dimensions_px:[w.width,w.height],natural:[img.naturalWidth,img.naturalHeight],drawn_roi:[(w.left-i.left)/i.width,(w.top-i.top)/i.height,w.width/i.width,w.height/i.height],image_aspect_ratio_preserved:Math.abs(i.width/i.height-img.naturalWidth/img.naturalHeight)<.001};}),overflow:document.documentElement.scrollWidth>window.innerWidth,device_pixel_ratio:window.devicePixelRatio,roi:JSON.parse(document.getElementById('page-data').textContent).board.members.map(member=>member.roi)}));
      }finally{await restoreGridOrigin(page,normalization);}
      actual.members.forEach((member,index)=>{member.readability_diagnostics=readabilityMetrics(member.natural,actual.roi[index],member.display_css_dimensions_px,actual.device_pixel_ratio);});
      if(actual.members.length!==board.members.length)errors.push({board_id:board.board_id,error:'displayed_count_mismatch'});
      if(JSON.stringify(actual.members.map(m=>m.image_id))!==JSON.stringify(board.members.map(m=>m.image_id)))errors.push({board_id:board.board_id,error:'image_order_mismatch'});
      if(JSON.stringify(actual.members.map(m=>m.original_sha))!==JSON.stringify(board.members.map(m=>m.sha256)))errors.push({board_id:board.board_id,error:'displayed_image_SHA_mismatch'});
      if(JSON.stringify(actual.roi)!==JSON.stringify(board.members.map(m=>m.roi)))errors.push({board_id:board.board_id,error:'ROI_mismatch'});
      if(actual.members.some((member,index)=>member.drawn_roi.some((value,axis)=>Math.abs(value-board.members[index].roi[axis])>.001)||!member.image_aspect_ratio_preserved))errors.push({board_id:board.board_id,error:'rendered_crop_geometry_or_aspect_mismatch'});
      await page.locator('.tile-open').first().click();await page.waitForFunction(()=>{const img=document.getElementById('original-image');return img.complete&&img.naturalWidth>0&&!document.getElementById('original-modal').hidden;});
      const modal=await page.evaluate(()=>({open:!document.getElementById('original-modal').hidden,loaded:document.getElementById('original-image').naturalWidth>0,roi:document.getElementById('roi-outline').getAttribute('style'),evidence_roi:document.getElementById('evidence-outline')?.getAttribute('style')||null,evidence_visible:document.getElementById('evidence-outline')?.hidden===false,selected_view:document.getElementById('selected-view')?.textContent||'',emotion_reason:document.getElementById('member-emotion')?.textContent||'',common_design_emotion:document.querySelector('.emotion-name')?.textContent||'',article_links:document.querySelectorAll('#source-list a').length}));await page.keyboard.press('Escape');const closed=await page.locator('#original-modal').evaluate(node=>node.hidden);
      const first=board.members[0];if(first.display_bbox&&JSON.stringify(first.roi)!==JSON.stringify(first.display_bbox))errors.push({board_id:board.board_id,error:'selected_display_not_used'});
      if(first.display_scope){const expectedView=[first.primary_subject?.identity,first.display_scope==='representative_detail'?'代表性局部':'对象整体',first.crop_reason].filter(Boolean).join(' · ');if(modal.selected_view!==expectedView)errors.push({board_id:board.board_id,error:'selected_object_view_explanation_missing'});}
      if(first.evidence_bbox&&JSON.stringify(first.evidence_bbox)!==JSON.stringify(first.roi)&&!modal.evidence_visible)errors.push({board_id:board.board_id,error:'evidence_outline_not_separated'});
      if(modal.common_design_emotion!==(board.common_design_emotion||'')||modal.emotion_reason!==(first.current_target_review?.emotion_reason||''))errors.push({board_id:board.board_id,error:'reviewed_emotion_evidence_not_displayed'});
      await page.locator('#feedback-decision').selectOption('comment_only');await page.locator('#feedback-comment').fill('离线功能核验，不是设计师审美结论');await page.locator('#save-feedback').click();const feedbackSaved=await page.locator('#feedback-message').innerText();
      const [download]=await Promise.all([page.waitForEvent('download'),page.locator('#export-board-feedback').click()]);const feedbackExport=JSON.parse(fs.readFileSync(await download.path(),'utf8'));const feedbackExportValid=feedbackExport.feedback?.[0]?.board_id===board.board_id&&feedbackExport.feedback[0].decision==='comment_only'&&JSON.stringify(feedbackExport.feedback[0].image_sha256)===JSON.stringify(board.members.map(member=>member.sha256));
      await page.setViewportSize({width:390,height:844});await ready(page);const mobile=await page.evaluate(()=>({overflow:document.documentElement.scrollWidth>innerWidth,loaded:[...document.querySelectorAll('.tile img')].every(img=>img.complete&&img.naturalWidth>0),count:document.querySelectorAll('.tile').length}));
      // 功能验证的本机反馈仅在临时浏览器上下文内，不写回交付的人审状态。
      const result={board_id:board.board_id,layout_identity:actualLayoutIdentity,html_ref:fileRef(html),screenshot_ref:fileRef(png),delivery_manifest_ref:fileRef(manifestPath),viewport:[1440,1080],members:board.members,actual_display:actual,capture_position_normalization:normalization,modal:{...modal,closed_by_escape:closed},feedback_form_usable:feedbackSaved.includes('已保存'),feedback_export_verified:feedbackExportValid,feedback_input_is_synthetic_functional_test:true,mobile,page_errors:pageErrors,external_image_requests:external,visual_pass_awarded:false};
      const passed=!actual.overflow&&!mobile.overflow&&mobile.loaded&&modal.open&&modal.loaded&&closed&&feedbackExportValid&&!pageErrors.length&&!external.length&&actual.members.every(member=>member.window[0]>0&&member.window[1]>0);
      result.functional_status=passed?'passed':'failed';if(!passed)errors.push({board_id:board.board_id,error:'functional_check_failed'});write(path.join(output,board.board_id+'.png.json'),result);results.push(result);await page.close();
    }
    const page=await browser.newPage({viewport:{width:1440,height:1080}});await page.goto(pathToFileURL(path.join(delivery,'index.html')).href);await ready(page);const index=[];
    for(const viewport of [{width:1440,height:1080},{width:390,height:844}]){
      await page.setViewportSize(viewport);await ready(page);const counts={};for(const filter of ['ID','CMF','all']){await page.locator('[data-filter="'+filter+'"]').click();counts[filter]=await page.locator('.board-card:not([hidden])').count();}
      // 诊断默认折叠但链接必须完整；另核展开后可浏览，不将它计入视觉支持结果。
      const diagnostic=page.locator('.diagnostic-details');const diagnosticCount=await diagnostic.count();const collapsed=diagnosticCount?!(await diagnostic.first().evaluate(node=>node.open)):true;
      const expectedSupported=manifest.boards.filter(board=>board.validation_display.some(row=>row.key==='visual'&&row.state==='passed')).length;
      const shownSupported=await page.locator('[data-result-group="usable"] .board-card').count();
      if(!collapsed||shownSupported!==expectedSupported)errors.push({error:'diagnostic_or_supported_result_separation_failed',viewport});
      const overflow=await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth);const indexPng=path.join(output,'index-'+viewport.width+'.png');await page.screenshot({path:indexPng,fullPage:true});
      let expandedCount=await page.locator('.board-card:visible').count();if(diagnosticCount){await diagnostic.locator('summary').click();await ready(page);expandedCount=await page.locator('.board-card:visible').count();await diagnostic.locator('summary').click();}
      index.push({viewport,counts,overflow,diagnostic_collapsed:collapsed,visually_supported:shownSupported,expanded_count:expandedCount,screenshot_ref:fileRef(indexPng)});if(overflow||expandedCount!==manifest.boards.length||counts.all!==manifest.boards.length||counts.ID!==manifest.boards.filter(b=>b.branch==='ID').length||counts.CMF!==manifest.boards.filter(b=>b.branch==='CMF').length)errors.push({error:'index_filter_or_layout_failed',viewport});
    }
    await page.close();write(path.join(output,'capture-manifest.json'),{schema_version:'prism.dna_cluster_browser_capture.v1',created_at:new Date().toISOString(),delivery_manifest_ref:fileRef(manifestPath),capture_script_ref:fileRef(__filename),status:errors.length?'failed':'passed',boards:results.map(result=>({board_id:result.board_id,screenshot_ref:result.screenshot_ref,functional_status:result.functional_status})),index,errors,model_calls:0,visual_pass_awarded:false});
    write(path.join(output,'capture-index.json'),{schema_version:'prism.dna_cluster_capture_index.v1',delivery_manifest_ref:fileRef(manifestPath),boards:results.map(result=>({board_id:result.board_id,png_path:result.screenshot_ref.path,screenshot_ref:result.screenshot_ref,sidecar_ref:fileRef(path.join(output,result.board_id+'.png.json'))}))});
    console.log(JSON.stringify({boards:results.length,status:errors.length?'failed':'passed',output,errors}));if(errors.length)process.exitCode=1;
  }finally{await browser.close();}
}
module.exports={readabilityMetrics};
if(require.main===module)main().catch(error=>{console.error(error.stack||error);process.exit(1);});
