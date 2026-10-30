(() => {
  'use strict';
  const data = JSON.parse(document.getElementById('collection-data').textContent);
  const byId = id => document.getElementById(id);
  // 排名只改变展示顺序，不改集合身份、板内成员或标注导入导出的来源顺序。
  function readRanking(ranking) {
    if (!ranking || typeof ranking !== 'object' || Array.isArray(ranking) ||
        ranking.collection_identity !== data.identity || !Array.isArray(ranking.entries) ||
        ranking.entries.length !== data.boards.length) return null;
    const boardIds = new Set(data.boards.map(board => board.id));
    const ranks = new Set();
    const entries = new Map();
    for (const entry of ranking.entries) {
      if (!entry || typeof entry !== 'object' || Array.isArray(entry) ||
          !boardIds.has(entry.board_id) || entries.has(entry.board_id) ||
          !Number.isInteger(entry.rank) || entry.rank < 1 || entry.rank > data.boards.length ||
          ranks.has(entry.rank) || typeof entry.reason !== 'string' || !entry.reason.trim()) return null;
      ranks.add(entry.rank);
      entries.set(entry.board_id, entry);
    }
    return entries;
  }
  const ranking = readRanking(data.ranking);
  const displayedBoards = ranking
    ? [...data.boards].sort((left, right) => ranking.get(left.id).rank - ranking.get(right.id).rank)
    : data.boards;
  if (data.ranking) {
    byId('ranking-summary').hidden = false;
    if (!ranking) byId('ranking-summary').textContent = '排名资料不完整或与当前集合不符，暂沿用原来源顺序；图片及已有标注不受影响。';
  }
  const tiles = new Map(data.boards.flatMap(board => board.images.map(image => [image.id, { board, image }])));
  const storageKey = 'prism-image-rejections:' + data.identity;
  let feedback = {};
  let currentFilter = 'all';
  let activeBoard = null;
  let activeIndex = 0;
  let toastTimer;
  const viewer = byId('viewer');
  const imageNodes = new Map();
  const cropNodes = [];
  byId('board-total').textContent = String(data.board_count);
  byId('image-total').textContent = String(data.image_count);

  function toast(message) {
    byId('toast').textContent = message;
    byId('toast').classList.add('visible');
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => byId('toast').classList.remove('visible'), 2300);
  }

  // 只接收当前集合中真实图片ID的拒绝记录；未标注始终不等于通过。
  function validRecords(records) {
    const result = {};
    if (!records || typeof records !== 'object' || Array.isArray(records)) return result;
    for (const [id, record] of Object.entries(records)) {
      if (tiles.has(id) && record && record.status === 'rejected' && typeof record === 'object') {
        result[id] = { status: 'rejected', reason: typeof record.reason === 'string' ? record.reason : '', updated_at: typeof record.updated_at === 'string' ? record.updated_at : '' };
      }
    }
    return result;
  }
  try {
    feedback = validRecords(JSON.parse(localStorage.getItem(storageKey) || '{}'));
  } catch {
    byId('storage-note').textContent = '当前浏览器无法读取已保存标注；请使用导出标注保存记录。';
  }

  function save() {
    try {
      localStorage.setItem(storageKey, JSON.stringify(feedback));
    } catch {
      byId('storage-note').textContent = '当前浏览器无法保存标注。请导出记录，避免关闭后丢失。';
      toast('保存失败，请导出标注');
    }
    update();
  }

  function update() {
    for (const [id, container] of imageNodes) {
      const rejected = Boolean(feedback[id]);
      container.classList.toggle('is-rejected', rejected);
      container.querySelector('.mark-image').setAttribute('aria-pressed', String(rejected));
      container.querySelector('.reject-overlay').hidden = !rejected;
      container.querySelector('.reject-badge').hidden = !rejected;
    }
    let visibleBoards = 0;
    let visibleImages = 0;
    for (const board of data.boards) {
      const count = board.images.filter(image => feedback[image.id]).length;
      const counter = byId('count-' + board.id);
      counter.textContent = count + ' / ' + board.images.length + ' 不通过';
      counter.classList.toggle('has-rejections', count > 0);
      const visible = currentFilter === 'all' || currentFilter === board.source;
      byId(board.id).hidden = !visible;
      if (visible) { visibleBoards++; visibleImages += board.images.length; }
    }
    byId('rejected-total').textContent = String(Object.keys(feedback).length);
    byId('progress').textContent = '当前显示 ' + visibleBoards + ' 板 · ' + visibleImages + ' 个图片位置。红框表示你标记的不通过。';
    if (activeBoard && viewer.open) syncViewerFeedback();
  }

  function toggle(image) {
    if (feedback[image.id]) {
      delete feedback[image.id];
      toast('已取消不通过标注');
    } else {
      feedback[image.id] = { status: 'rejected', reason: '', updated_at: new Date().toISOString() };
      toast('已标记不通过');
    }
    save();
  }

  function make(tag, className, text) {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text) node.textContent = text;
    return node;
  }
  function percentageBox(node, box) {
    const [x, y, width, height] = box;
    Object.assign(node.style, { left: x * 100 + '%', top: y * 100 + '%', width: width * 100 + '%', height: height * 100 + '%' });
  }
  function cropStyle(img, roi) {
    const [x, y, width, height] = roi;
    Object.assign(img.style, { width: 100 / width + '%', height: 100 / height + '%', left: -100 * x / width + '%', top: -100 * y / height + '%' });
  }
  function addImage(board, image, index, nativeLayout) {
    const container = make('div', nativeLayout ? 'ppt-photo' : 'image-tile');
    container.dataset.imageId = image.id;
    const button = make('button', 'mark-image');
    button.type = 'button';
    button.setAttribute('aria-label', board.title + ' · ' + image.label + '：点击标记或取消不通过');
    button.setAttribute('aria-pressed', 'false');
    const frame = make('span', 'crop-frame');
    const img = make('img');
    img.src = image.preview;
    img.alt = image.label;
    img.loading = 'lazy';
    img.decoding = 'async';
    cropStyle(img, image.preview_roi);
    frame.append(img);
    if (nativeLayout) {
      percentageBox(container, image.box);
      button.append(frame);
    } else {
      const space = make('span', 'crop-space');
      const override = image.layout_override;
      if (override) {
        container.style.setProperty('--tile-span', override.columns);
        container.style.setProperty('--mobile-span', 2);
        container.style.setProperty('--tile-height', override.height + 'px');
        container.style.setProperty('--mobile-tile-height', override.mobile_height + 'px');
      }
      space.append(frame);
      button.append(space);
      const record = { space, frame, image };
      cropNodes.push(record);
      cropObserver.observe(space);
    }
    const overlay = make('span', 'reject-overlay');
    const badge = make('span', 'reject-badge', '不通过');
    overlay.hidden = true; badge.hidden = true;
    button.append(overlay, badge);
    button.addEventListener('click', () => toggle(image));
    const zoom = make('button', 'zoom', '放大');
    zoom.type = 'button';
    zoom.setAttribute('aria-label', '放大 ' + image.label + ' 原图');
    zoom.addEventListener('click', () => openViewer(board, index));
    container.append(button);
    if (nativeLayout) container.append(zoom);
    else {
      const footer = make('div', 'tile-footer');
      footer.append(make('span', 'tile-label', String(index + 1).padStart(2, '0') + ' · ' + image.label), zoom);
      container.append(footer);
    }
    imageNodes.set(image.id, container);
    return container;
  }

  function fitCrop(record) {
    const roi = record.image.preview_roi;
    const dimensions = record.image.preview_dimensions || record.image.dimensions;
    const ratio = dimensions[0] * roi[2] / (dimensions[1] * roi[3]);
    const width = Math.min(record.space.clientWidth, record.space.clientHeight * ratio);
    record.frame.style.width = width + 'px';
    record.frame.style.height = width / ratio + 'px';
  }
  const cropObserver = new ResizeObserver(() => cropNodes.forEach(fitCrop));

  for (const board of displayedBoards) {
    const section = make('section', 'board');
    section.id = board.id;
    section.dataset.source = board.source;
    const heading = make('div', 'board-heading');
    const titles = make('div');
    const rank = ranking?.get(board.id);
    if (rank) {
      section.dataset.rank = String(rank.rank);
      titles.append(make('p', 'board-rank', '第 ' + rank.rank + ' 名'));
    }
    titles.append(make('p', 'source-label', board.source_label + ' · ' + (rank ? '来源编号 ' : '') + String(board.source_index).padStart(2, '0')), make('h2', '', board.title));
    if (board.subtitle) titles.append(make('p', 'board-subtitle', board.subtitle));
    const counter = make('span', 'board-rejected');
    counter.id = 'count-' + board.id;
    heading.append(titles, counter);
    section.append(heading);
    if (rank) section.append(make('p', 'rank-reason', rank.reason));
    section.append(make('p', 'source-state', board.source_state), make('p', 'board-note', board.notes));
    if (board.source_url) {
      const link = make('a', 'source-entry', '查看来源网页 ↗');
      link.href = board.source_url; link.target = '_blank'; link.rel = 'noopener';
      section.append(link);
    }
    if (board.layout === 'ppt') {
      section.append(make('p', 'ppt-hint', 'PPT 保留原版布局，窄屏可在板内横向滑动。'));
      const scroll = make('div', 'ppt-scroll');
      const canvas = make('div', 'ppt-canvas');
      canvas.style.aspectRatio = String(board.aspect);
      for (const layer of board.layers) {
        if (layer.type === 'image') {
          const index = board.images.findIndex(image => image.id === layer.image_id);
          canvas.append(addImage(board, board.images[index], index, true));
        } else {
          const text = make('p', 'ppt-text', layer.text);
          percentageBox(text, layer.box);
          Object.assign(text.style, { fontSize: 'calc(100cqw * ' + layer.font_ratio + ')', fontWeight: layer.bold ? '700' : '400', color: layer.color, textAlign: layer.align });
          canvas.append(text);
        }
      }
      scroll.append(canvas); section.append(scroll);
    } else {
      const grid = make('div', 'image-grid');
      grid.style.setProperty('--board-cols', board.columns || 4);
      grid.style.setProperty('--tile-height', (board.tile_height || 245) + 'px');
      grid.style.setProperty('--mobile-tile-height', (board.mobile_tile_height || 165) + 'px');
      board.images.forEach((image, index) => grid.append(addImage(board, image, index, false)));
      section.append(grid);
    }
    byId('boards').append(section);
  }

  function syncViewerFeedback() {
    const image = activeBoard.images[activeIndex];
    const record = feedback[image.id];
    byId('viewer-reject').textContent = record ? '取消不通过标注' : '标记不通过';
    byId('viewer-reject').setAttribute('aria-pressed', String(Boolean(record)));
    byId('reason').disabled = !record;
    byId('reason').value = record?.reason || '';
  }
  function showOriginal() {
    const image = activeBoard.images[activeIndex];
    byId('original').src = image.original;
    byId('original').alt = image.label + ' 完整原图';
    byId('viewer-title').textContent = image.label;
    byId('viewer-board').textContent = activeBoard.source_label + ' · ' + activeBoard.title;
    byId('viewer-scope').textContent = image.scope;
    byId('viewer-dimensions').textContent = image.dimensions.join(' × ') + ' 像素';
    byId('viewer-count').textContent = (activeIndex + 1) + ' / ' + activeBoard.images.length;
    byId('previous').disabled = activeIndex === 0;
    byId('next').disabled = activeIndex === activeBoard.images.length - 1;
    byId('open-original').href = image.original;
    byId('source-links').replaceChildren();
    for (const source of image.sources) {
      const link = make('a', '', source.title + ' ↗');
      link.href = source.url; link.target = '_blank'; link.rel = 'noopener';
      byId('source-links').append(link);
    }
    syncViewerFeedback();
  }
  function openViewer(board, index) {
    activeBoard = board; activeIndex = index;
    showOriginal(); viewer.showModal();
    document.body.style.overflow = 'hidden';
  }
  byId('close-viewer').onclick = () => viewer.close();
  viewer.addEventListener('close', () => { document.body.style.overflow = ''; byId('original').removeAttribute('src'); });
  viewer.addEventListener('click', event => {
    if (event.target !== viewer) return;
    const rect = viewer.getBoundingClientRect();
    if (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom) viewer.close();
  });
  byId('viewer-reject').onclick = () => toggle(activeBoard.images[activeIndex]);
  byId('reason').addEventListener('change', () => {
    const id = activeBoard.images[activeIndex].id;
    if (feedback[id]) { feedback[id].reason = byId('reason').value.trim(); feedback[id].updated_at = new Date().toISOString(); save(); }
  });
  function move(delta) {
    const index = activeIndex + delta;
    if (index >= 0 && index < activeBoard.images.length) { activeIndex = index; showOriginal(); }
  }
  byId('previous').onclick = () => move(-1);
  byId('next').onclick = () => move(1);
  viewer.addEventListener('keydown', event => {
    if (event.target.tagName === 'TEXTAREA') return;
    if (event.key === 'ArrowLeft' || event.key === 'ArrowRight') { event.preventDefault(); move(event.key === 'ArrowLeft' ? -1 : 1); }
  });

  for (const button of document.querySelectorAll('[data-source]')) {
    // 只绑定筛选按钮，图板本身的data-source用于来源追溯。
    if (button.tagName !== 'BUTTON') continue;
    button.addEventListener('click', () => {
      currentFilter = button.dataset.source;
      document.querySelectorAll('.filters button').forEach(item => item.setAttribute('aria-pressed', String(item === button)));
      update(); cropNodes.forEach(fitCrop);
    });
  }
  byId('export').onclick = () => {
    const records = data.boards.flatMap(board => board.images.map(image => ({
      board_id: board.id, board_title: board.title, source: board.source, image_id: image.image_id,
      instance_id: image.id, image_sha256: image.sha256, unit_id: image.unit_id || null,
      ppt_shape_id: image.ppt_shape_id || null, roi: image.roi,
      status: feedback[image.id] ? 'rejected' : 'unmarked',
      reason: feedback[image.id]?.reason || '', updated_at: feedback[image.id]?.updated_at || null,
    })));
    const payload = { schema_version: 'prism.image_rejection_feedback.v1', collection_identity: data.identity,
      exported_at: new Date().toISOString(), storage: 'this_browser', records };
    const url = URL.createObjectURL(new Blob([JSON.stringify(payload, null, 2) + '\n'], { type: 'application/json' }));
    const link = make('a'); link.href = url; link.download = 'moodboard-image-rejections.json'; link.click();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  };
  byId('import').onclick = () => byId('import-file').click();
  byId('import-file').addEventListener('change', async event => {
    const file = event.target.files[0];
    if (!file) return;
    try {
      const payload = JSON.parse(await file.text());
      if (payload.schema_version !== 'prism.image_rejection_feedback.v1' || payload.collection_identity !== data.identity || !Array.isArray(payload.records)) throw Error('记录不是当前这组图板的标注');
      const records = {};
      for (const record of payload.records) {
        const tile = tiles.get(record.instance_id);
        if (!tile || tile.image.sha256 !== record.image_sha256 || tile.board.id !== record.board_id || !['rejected', 'unmarked'].includes(record.status)) throw Error('图片身份与当前图板不一致');
        if (record.status === 'rejected') records[record.instance_id] = record;
      }
      if (!confirm('用导入记录替换当前浏览器的全部标注？')) return;
      feedback = validRecords(records); save(); toast('已导入标注');
    } catch (error) { toast('导入失败：' + error.message); }
    finally { event.target.value = ''; }
  });
  byId('reset').onclick = () => {
    if (Object.keys(feedback).length && confirm('清空此页全部不通过标注？建议先导出。')) { feedback = {}; save(); toast('已清空标注'); }
  };
  update(); cropNodes.forEach(fitCrop);
  window.__moodboardReviewReady = true;
})();
