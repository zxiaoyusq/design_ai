(function () {
  'use strict';

  var startup = document.getElementById('app-startup');
  var title = document.getElementById('app-startup-title');
  var message = document.getElementById('app-startup-message');
  var button = document.getElementById('app-startup-reload');
  var app = document.getElementById('app');
  var ready = false;
  var failed = false;
  var recovering = false;
  var moduleFailure = /failed to fetch dynamically imported module|importing a module script failed|error loading dynamically imported module|loading (?:css )?chunk [\w-]+ failed|unable to preload css for|failed to load module script/i;

  function reload() {
    if (recovering) return;
    recovering = true;
    var url = new URL(window.location.href);
    // 仅由用户点击触发；保留当前查询、锚点及浏览器工作区数据。
    url.searchParams.set('__app_cache', String(Date.now()));
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
    // 模块加载失败只提示，避免网络波动时擅自重载并丢失未保存的输入。
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
