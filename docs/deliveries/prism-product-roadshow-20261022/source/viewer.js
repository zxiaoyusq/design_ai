(() => {
  'use strict';
  let startupFailed = false;
  function initialize() {
    // 缺少交互所需能力时维持默认阅读模式，不隐藏正文或要求降低浏览器安全设置。
    if (!window.matchMedia || !window.HTMLDialogElement || typeof HTMLDialogElement.prototype.showModal !== 'function') return;
    const talk = JSON.parse(document.getElementById('talk-data').textContent);
    const slides = [...document.querySelectorAll('.slide')];
    const mainCount = talk.mainCount;
    const backupCount = slides.length - mainCount;
    const totalSeconds = talk.targetSeconds + talk.qaSeconds;
    const byId = id => document.getElementById(id);
    const escape = value => String(value).replace(/[&<>"']/g, char => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[char]));
    const time = seconds => `${String(Math.floor(seconds / 60)).padStart(2, '0')}:${String(seconds % 60).padStart(2, '0')}`;
    let current = 0;
    let reading = matchMedia('(max-width: 900px)').matches;
    let remaining = totalSeconds;
    let deadline = 0;
    let timerRunning = false;
    let restoreReading = false;
    let scrollFrame = 0;
    let guessTimer = null;
    const starts = [];
    talk.slides.slice(0, mainCount).reduce((total, slide) => { starts.push(total); return total + slide.seconds; }, 0);

    function resize() {
      const scale = Math.min((innerWidth - 36) / 1600, (innerHeight - 106) / 900);
      document.documentElement.style.setProperty('--scale', String(Math.max(.1, scale)));
    }

    function updateNotes() {
      const slide = talk.slides[current];
      const backup = current >= mainCount;
      const label = backup ? `B${current - mainCount + 1}` : String(current + 1).padStart(2, '0');
      const timing = backup ? `按问题选用 · 建议 ${slide.seconds} 秒，不计入主讲` : `${time(starts[current])}–${time(starts[current] + slide.seconds)} · 本页 ${slide.seconds} 秒`;
      byId('notes-heading').textContent = `${label} / ${slide.title}`;
      byId('notes-body').innerHTML = `<p class="speaker-cue">${timing}<br>${escape(slide.cue)}</p>` + slide.paragraphs.map(text => `<p>${escape(text)}</p>`).join('') + (slide.bridge ? `<p class="note-bridge">转场：${escape(slide.bridge)}</p>` : '');
      byId('notes-prev').disabled = current === 0;
      byId('notes-next').disabled = current === slides.length - 1;
      byId('notes-dialog').scrollTop = 0;
    }

    function go(index, scroll = true) {
      if (startupFailed) return;
      current = Math.max(0, Math.min(slides.length - 1, index));
      // 离开猜图页即停止互动计时，避免答案页仍在播报倒计时；不会自动揭晓。
      if (slides[current].id !== 'slide-6' && guessTimer !== null) {
        clearInterval(guessTimer);
        guessTimer = null;
        byId('guess-timer').textContent = '15 秒选择';
        byId('guess-timer').setAttribute('aria-label', '开始15秒观众选择时间');
      }
      slides.forEach((slide, i) => {
        slide.classList.toggle('active', i === current);
        slide.setAttribute('aria-hidden', String(!reading && i !== current));
        slide.inert = !reading && i !== current;
      });
      const backup = current >= mainCount;
      byId('counter').textContent = backup ? `备答 ${current - mainCount + 1}/${backupCount}` : `主讲 ${String(current + 1).padStart(2, '0')}/${mainCount}`;
      byId('prev').disabled = current === 0;
      byId('next').disabled = current === slides.length - 1;
      byId('progress-bar').style.width = `${(backup ? (current - mainCount + 1) / backupCount : (current + 1) / mainCount) * 100}%`;
      byId('progress-bar').parentElement.classList.toggle('backup-progress', backup);
      byId('live-status').textContent = `第 ${current + 1} 页，${talk.slides[current].title}`;
      document.querySelectorAll('[data-slide]').forEach(button => button.setAttribute('aria-current', String(Number(button.dataset.slide) === current)));
      // 本地文件也可以翻页；部分浏览器限制 file: 下改历史记录时，只略过地址同步。
      try { history.replaceState(null, '', `#slide-${current + 1}`); } catch (_) { /* 展示不依赖地址写入。 */ }
      if (reading && scroll) slides[current].scrollIntoView({behavior:'auto', block:'start'});
      if (byId('notes-dialog').open) updateNotes();
    }

    function setReading(value) {
      reading = value;
      document.body.classList.toggle('reading', reading);
      byId('reading-button').textContent = reading ? '演示' : '阅读';
      byId('reading-button').setAttribute('aria-pressed', String(reading));
      resize();
      go(current);
    }

    function openDialog(id) {
      document.querySelectorAll('dialog[open]').forEach(dialog => dialog.close());
      if (id === 'notes-dialog') updateNotes();
      byId(id).showModal();
    }

    async function fullscreen() {
      try {
        if (document.fullscreenElement) await document.exitFullscreen();
        else await document.documentElement.requestFullscreen();
      } catch (_) {
        byId('live-status').textContent = '此浏览器不支持页面全屏，可以使用浏览器的全屏功能。';
      }
    }

    function updateTimer() {
      if (timerRunning) remaining = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
      if (remaining === 0) timerRunning = false;
      const label = remaining === 0 ? '结束' : timerRunning ? (remaining <= talk.qaSeconds ? '问答' : '主讲') : (remaining === totalSeconds ? '开始' : '继续');
      byId('timer-button').textContent = `${time(remaining)} ${label}`;
      byId('timer-button').classList.toggle('warning', remaining <= talk.qaSeconds);
      byId('timer-button').setAttribute('aria-label', `${timerRunning ? '暂停' : '开始'}计时，剩余 ${Math.floor(remaining / 60)} 分 ${remaining % 60} 秒`);
    }

    byId('prev').addEventListener('click', () => go(current - 1));
    byId('next').addEventListener('click', () => go(current + 1));
    // 关键关系始终完整显示，演讲者可按现场节奏重播路径。减少动态效果时保留静态图。
    const motionTimers = new Map();
    document.querySelectorAll('[data-motion]').forEach(button => {
      button.addEventListener('click', () => {
        const target = byId(button.getAttribute('aria-controls'));
        clearTimeout(motionTimers.get(target));
        target.classList.remove('motion-playing');
        if (matchMedia('(prefers-reduced-motion: reduce)').matches) return;
        void target.offsetWidth;
        target.classList.add('motion-playing');
        motionTimers.set(target, setTimeout(() => target.classList.remove('motion-playing'), 2400));
      });
    });
    document.querySelector('[data-scope-toggle]').addEventListener('click', event => {
      const button = event.currentTarget;
      const focused = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', String(focused));
      button.textContent = focused ? '一期范围已突出' : '突出一期范围';
      byId('phase-map').classList.toggle('focus-phase-one', focused);
    });
    byId('guess-timer').addEventListener('click', () => {
      clearInterval(guessTimer);
      const until = performance.now() + 15000;
      const button = byId('guess-timer');
      button.textContent = '15 秒 · 选择中';
      button.setAttribute('aria-label', '选择计时已开始，15秒后可手动揭晓；再次点击重新计时');
      guessTimer = setInterval(() => {
        const seconds = Math.max(0, Math.ceil((until - performance.now()) / 1000));
        button.textContent = seconds ? `${seconds} 秒 · 选择中` : '时间到 · 可揭晓';
        if (!seconds) {
          clearInterval(guessTimer);
          guessTimer = null;
          button.setAttribute('aria-label', '选择时间到，可手动揭晓；点击重新计时');
          byId('live-status').textContent = '观众选择时间到，可手动揭晓。';
        }
      }, 200);
    });
    // 产品链路始终完整可见；点击节点只更新说明，不把并行双板误画成串行步骤。
    document.querySelectorAll('[data-pipeline-step]').forEach(button => {
      button.addEventListener('click', () => {
        document.querySelectorAll('[data-pipeline-step]').forEach(item => {
          item.setAttribute('aria-pressed', String(item === button));
        });
        document.querySelectorAll('[data-pipeline-panel]').forEach(panel => {
          panel.hidden = panel.dataset.pipelinePanel !== button.dataset.pipelineStep;
        });
      });
    });
    byId('notes-prev').addEventListener('click', () => go(current - 1));
    byId('notes-next').addEventListener('click', () => go(current + 1));
    byId('notes-button').addEventListener('click', () => openDialog('notes-dialog'));
    byId('overview-button').addEventListener('click', () => openDialog('overview-dialog'));
    // 备答是主讲之后的真实页面，前后翻页即可展示，不再藏在问答弹层里。
    byId('qa-button').addEventListener('click', () => go(mainCount));
    document.querySelectorAll('[data-target]').forEach(button => button.addEventListener('click', () => go(Number(button.dataset.target) - 1)));
    byId('sources-button').addEventListener('click', () => openDialog('sources-dialog'));
    byId('mobile-sources').addEventListener('click', () => openDialog('sources-dialog'));
    byId('reading-button').addEventListener('click', () => setReading(!reading));
    byId('fullscreen-button').addEventListener('click', fullscreen);
    byId('timer-button').addEventListener('click', () => {
      if (remaining === 0) remaining = totalSeconds;
      if (timerRunning) { updateTimer(); timerRunning = false; }
      else { deadline = performance.now() + remaining * 1000; timerRunning = true; }
      updateTimer();
    });
    byId('reset-timer').addEventListener('click', () => { timerRunning = false; remaining = totalSeconds; updateTimer(); });
    byId('print-button').addEventListener('click', () => { byId('sources-dialog').close(); window.print(); });
    // 打印始终使用投屏版的 16:9 排版，打印结束后恢复阅读模式。
    window.addEventListener('beforeprint', () => { restoreReading = reading; document.body.classList.remove('reading'); });
    window.addEventListener('afterprint', () => document.body.classList.toggle('reading', restoreReading));

    byId('overview-list').innerHTML = talk.slides.map((slide, i) => {
      const group = i === 0 ? `<p class="overview-group">主讲 · ${mainCount} 页 / 12 分钟</p>` : i === mainCount ? `<p class="overview-group">备用 · ${backupCount} 页 / 提问时向后展示</p>` : '';
      const label = i < mainCount ? `${String(i + 1).padStart(2,'0')} · ${time(starts[i])}–${time(starts[i] + slide.seconds)}` : `B${i - mainCount + 1} · 按需 ${slide.seconds} 秒`;
      return `${group}<button type="button" data-slide="${i}"><span>${label}</span>${escape(slide.title)}</button>`;
    }).join('');
    byId('overview-list').addEventListener('click', event => {
      const button = event.target.closest('[data-slide]');
      if (!button) return;
      byId('overview-dialog').close();
      go(Number(button.dataset.slide));
    });
    byId('sources-body').innerHTML = talk.sources.map(source => `<h3 class="source-title">${escape(source.label)}</h3><p class="source-detail">${escape(source.detail)}</p>`).join('') + `<p class="help-line">12 分钟主讲含约 15 秒猜图互动，预留 3 分钟问答。主讲后仅 4 张备用页，按问题选择。计时不自动翻页，剩余 3 分钟提示问答。</p><p class="source-detail">情绪板原图、DNA 截图、样式和脚本均已内嵌，可离线使用。猜图时不要投屏讲稿与目录；讲稿请在另一个设备查看。</p>`;
    document.querySelectorAll('[data-close]').forEach(button => button.addEventListener('click', () => button.closest('dialog').close()));
    document.querySelectorAll('dialog').forEach(dialog => dialog.addEventListener('click', event => {
      const rect = dialog.getBoundingClientRect();
      if (event.target === dialog && (event.clientX < rect.left || event.clientX > rect.right || event.clientY < rect.top || event.clientY > rect.bottom)) dialog.close();
    }));
    function setOriginalSize(enabled) {
      const viewport = byId('image-viewport');
      viewport.classList.toggle('natural-size', enabled);
      byId('image-size').setAttribute('aria-pressed', String(enabled));
      byId('image-size').textContent = enabled ? '适合屏幕' : '原始尺寸';
      viewport.scrollTop = 0;
      viewport.scrollLeft = 0;
    }
    byId('image-size').addEventListener('click', () => setOriginalSize(byId('image-size').getAttribute('aria-pressed') !== 'true'));
    byId('full-image').addEventListener('click', () => setOriginalSize(byId('image-size').getAttribute('aria-pressed') !== 'true'));
    document.querySelectorAll('[data-zoom]').forEach(button => button.addEventListener('click', () => {
      const original = button.querySelector('img');
      byId('image-heading').textContent = button.dataset.title || '完整原图';
      byId('full-image').src = original.src;
      byId('full-image').alt = original.alt;
      byId('image-caption').textContent = button.dataset.caption || '原图按原始比例完整展示。';
      setOriginalSize(false);
      openDialog('image-dialog');
    }));
    document.addEventListener('keydown', event => {
      if (event.ctrlKey || event.metaKey || event.altKey || document.querySelector('dialog[open]')) return;
      if (event.target.closest('input,textarea,select,[contenteditable]')) return;
      if (event.target.closest('[data-pan]') && ['ArrowLeft','ArrowRight'].includes(event.key)) return;
      if (event.key === ' ' && event.target.closest('button,a')) return;
      if (['ArrowRight','ArrowDown','PageDown',' '].includes(event.key)) { event.preventDefault(); go(current + 1); }
      if (['ArrowLeft','ArrowUp','PageUp'].includes(event.key)) { event.preventDefault(); go(current - 1); }
      if (event.key === 'Home') { event.preventDefault(); go(0); }
      if (event.key === 'End') { event.preventDefault(); go(slides.length - 1); }
      if (event.key.toLowerCase() === 'n') openDialog('notes-dialog');
      if (event.key.toLowerCase() === 'f') void fullscreen();
    });
    window.addEventListener('hashchange', () => {
      const match = location.hash.match(/^#slide-(\d+)$/);
      if (match) go(Number(match[1]) - 1);
    });
    window.addEventListener('resize', resize);
    window.addEventListener('scroll', () => {
      if (!reading || scrollFrame) return;
      scrollFrame = requestAnimationFrame(() => {
        scrollFrame = 0;
        // 长页阅读以靠近屏幕上缘的章节更新目录，不改变用户的滚动位置。
        const anchor = Math.min(170, innerHeight * .25);
        let found = 0;
        slides.forEach((slide, i) => { if (slide.getBoundingClientRect().top <= anchor) found = i; });
        if (found !== current) go(found, false);
      });
    }, {passive:true});
    const initial = location.hash.match(/^#slide-(\d+)$/);
    current = initial ? Math.max(0, Math.min(slides.length - 1, Number(initial[1]) - 1)) : 0;
    setReading(reading);
    updateTimer();
    setInterval(updateTimer, 500);
    document.documentElement.classList.add('viewer-ready');
  }

  try {
    initialize();
  } catch (error) {
    // 失败时恢复可阅读内容；包括初始化中途已经添加的 inert，不能留在正文上。
    startupFailed = true;
    document.documentElement.classList.remove('viewer-ready');
    document.body.classList.add('reading');
    document.querySelectorAll('.slide').forEach(slide => {
      slide.removeAttribute('inert');
      slide.removeAttribute('aria-hidden');
    });
    document.getElementById('fallback-status').textContent = '演示交互未能启动，已保留完整阅读模式。请向下滚动查看全部页面与图片。';
    console.warn('PRISM 演示初始化失败，已保留阅读模式。', error);
  }
})();
