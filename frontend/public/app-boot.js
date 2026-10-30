(function () {
  'use strict';

  var revision = '20261021-dna-preparation-2';
  var retryParameter = '__app_retry';
  var retryKey = 'design-ai:startup-retry:' + window.location.pathname;
  var startup = document.getElementById('app-startup');
  var title = document.getElementById('app-startup-title');
  var message = document.getElementById('app-startup-message');
  var button = document.getElementById('app-startup-reload');
  var app = document.getElementById('app');
  var ready = false;
  var failed = false;
  var recovering = false;
  var moduleFailure = /failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module|loading (?:css )?chunk [\w-]+ failed|unable to preload css for|failed to load module script/i;

  function wasRetried() {
    if (new URL(window.location.href).searchParams.get(retryParameter) === revision) return true;
    try { return window.sessionStorage.getItem(retryKey) === revision; }
    catch (_) { return false; }
  }

  function reload() {
    if (recovering) return;
    recovering = true;
    var url = new URL(window.location.href);
    // URL 标记在禁用会话存储时仍能阻断循环；只写本功能的键，不清理用户数据。
    url.searchParams.set(retryParameter, revision);
    url.searchParams.set('__app_cache', String(Date.now()));
    try { window.sessionStorage.setItem(retryKey, revision); } catch (_) {}
    window.location.replace(url.href);
  }

  function showFailure() {
    failed = true;
    startup.hidden = false;
    startup.setAttribute('role', 'alert');
    title.textContent = '页面加载失败';
    message.textContent = '页面资源未能完整加载，请重新加载页面；如果仍然失败，请稍后重试。';
  }

  function recoverModule() {
    if (recovering) return;
    showFailure();
    // 已正常显示的页面保留现场；仅启动阶段的资源加载失败自动重试一次。
    if (!ready && !wasRetried()) reload();
  }

  function moduleMessage(error) {
    return typeof error === 'string' ? error : error && error.message || '';
  }

  window.addEventListener('error', function (event) {
    var target = event.target;
    if (target && target.tagName === 'SCRIPT' && target.src) {
      if (new URL(target.src, window.location.href).origin === window.location.origin) recoverModule();
    } else if (moduleFailure.test(event.message || '')) recoverModule();
  }, true);

  window.addEventListener('unhandledrejection', function (event) {
    if (moduleFailure.test(moduleMessage(event.reason))) recoverModule();
  });

  // Router 会捕获懒加载异常，因此额外接收明确的模块故障消息，不拦截业务错误。
  window.addEventListener('app:module-load-error', function (event) {
    if (moduleFailure.test(moduleMessage(event.detail))) recoverModule();
  });

  button.onclick = reload;
  var timeout = window.setTimeout(function () {
    if (!ready && !failed) {
      title.textContent = '页面加载尚未完成';
      message.textContent = '可以继续等待，或重新加载页面。';
    }
  }, 20000);

  var observer = new window.MutationObserver(function () {
    // Router 初次等待异步页面时只有注释节点，不能把它视为已成功显示。
    if (!failed && app.children.length > 0) {
      ready = true;
      startup.hidden = true;
      window.clearTimeout(timeout);
      observer.disconnect();
    }
  });
  observer.observe(app, { childList: true });
})();
