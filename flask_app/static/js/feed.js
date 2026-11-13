/* Updates feed: posts, photos, videos, comments, saves, reels. Talks to /api/feed. */
(function () {
  'use strict';
  var root = document.getElementById('fd');
  if (!root) return;
  var cfg = { auth: root.dataset.auth === '1', admin: root.dataset.admin === '1', canPost: root.dataset.canPost === '1',
              tag: root.dataset.tag || '', focus: parseInt(root.dataset.post, 10) || 0, login: root.dataset.login || '/auth/login' };
  var tab = (location.hash === '#reels' || location.hash === '#saved') ? location.hash.slice(1) : 'feed';
  var posts = {}, next = null, loading = false, done = false, gen = 0, lastTap = { el: null, t: 0, timer: 0 };
  var list = q('#fd-list'), reels = q('#fd-reels'), sentinel = q('#fd-sentinel');

  function q(s, el) { return (el || root).querySelector(s); }
  function qa(s, el) { return Array.prototype.slice.call((el || root).querySelectorAll(s)); }
  function esc(t) { return String(t == null ? '' : t).replace(/[&<>"']/g, function (c) { return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]; }); }
  function rich(t) { return esc(t).replace(/#([A-Za-z0-9_]{2,30})/g, function (m, g) { return '<a class="fd-tag" href="/updates?tag=' + g.toLowerCase() + '">#' + g + '</a>'; }); }
  function safeUrl(u) { return /^(\/updates\/media\/|https:\/\/)/.test(u || '') ? u : ''; }
  function num(n) { n = n || 0; return n < 1000 ? String(n) : n < 10000 ? (n / 1000).toFixed(1).replace('.0', '') + 'K' : n < 1e6 ? Math.floor(n / 1000) + 'K' : (n / 1e6).toFixed(1).replace('.0', '') + 'M'; }
  function ago(iso) {
    var s = Math.max(0, (Date.now() - new Date(iso).getTime()) / 1000);
    if (s < 60) return 'Just now'; if (s < 3600) return Math.floor(s / 60) + 'm'; if (s < 86400) return Math.floor(s / 3600) + 'h';
    if (s < 604800) return Math.floor(s / 86400) + 'd'; if (s < 2592000) return Math.floor(s / 604800) + 'w';
    return new Date(iso).toLocaleDateString(undefined, { day: 'numeric', month: 'short', year: s > 31536000 ? 'numeric' : undefined });
  }
  var P = { heart: '<path d="M19 14c1.49-1.46 3-3.21 3-5.5A5.5 5.5 0 0 0 16.5 3c-1.76 0-3 .5-4.5 2-1.5-1.5-2.74-2-4.5-2A5.5 5.5 0 0 0 2 8.5c0 2.3 1.5 4.05 3 5.5l7 7Z"/>',
    comment: '<path d="M7.9 20A9 9 0 1 0 4 16.1L2 22Z"/>', share: '<path d="m22 2-7 20-4-9-9-4Z"/><path d="M22 2 11 13"/>',
    save: '<path d="m19 21-7-4-7 4V5a2 2 0 0 1 2-2h10a2 2 0 0 1 2 2v16z"/>', more: '<circle cx="12" cy="12" r="1"/><circle cx="19" cy="12" r="1"/><circle cx="5" cy="12" r="1"/>',
    x: '<path d="M18 6 6 18M6 6l12 12"/>', vol: '<path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="M15.5 8.5a5 5 0 0 1 0 7M19 5a10 10 0 0 1 0 14"/>',
    mute: '<path d="M11 5 6 9H2v6h4l5 4V5z"/><path d="m22 9-6 6M16 9l6 6"/>', image: '<rect width="18" height="18" x="3" y="3" rx="2"/><circle cx="9" cy="9" r="2"/><path d="m21 15-3.1-3.1a2 2 0 0 0-2.8 0L6 21"/>',
    video: '<path d="m16 13 5.2 3.5a.5.5 0 0 0 .8-.4V7.9a.5.5 0 0 0-.8-.4L16 11"/><rect width="14" height="12" x="2" y="6" rx="2"/>',
    pin: '<path d="M12 17v5"/><path d="M9 10.76a2 2 0 0 1-1.11 1.79l-1.78.9A2 2 0 0 0 5 15.24V16a1 1 0 0 0 1 1h12a1 1 0 0 0 1-1v-.76a2 2 0 0 0-1.11-1.79l-1.78-.9A2 2 0 0 1 15 10.76V7a1 1 0 0 1 1-1 2 2 0 0 0 0-4H8a2 2 0 0 0 0 4 1 1 0 0 1 1 1z"/>',
    book: '<path d="M4 19.5v-15A2.5 2.5 0 0 1 6.5 2H20v20H6.5a2.5 2.5 0 0 1 0-5H20"/>', check: '<circle cx="12" cy="12" r="10" fill="currentColor" stroke="none"/><path d="m8 12 3 3 5-6" stroke="#fff"/>',
    ghost: '<path d="M12 3a9 9 0 0 0-9 9v9l3-2 3 2 3-2 3 2 3-2 3 2v-9a9 9 0 0 0-9-9z"/><circle cx="9" cy="11" r="1"/><circle cx="15" cy="11" r="1"/>' };
  function ic(n) { return '<svg class="fd-i" viewBox="0 0 24 24" aria-hidden="true">' + P[n] + '</svg>'; }

  // ── network ────────────────────────────────────────────────────────────────
  function api(url, o) {
    o = o || {}; var h = { 'X-Requested-With': 'ssg-feed' }, body;
    if (o.json) { h['Content-Type'] = 'application/json'; body = JSON.stringify(o.json); }
    return fetch(url, { method: o.method || 'GET', headers: h, body: body, credentials: 'same-origin' }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (d) {
        if (!r.ok) { var e = new Error(d.error || 'Something went wrong.'); e.status = r.status; throw e; } return d; });
    });
  }
  function toast(msg, link) {
    var t = q('#fd-toast'); t.innerHTML = esc(msg) + (link ? ' <a href="' + esc(link.href) + '">' + esc(link.text) + '</a>' : '');
    t.classList.add('on'); clearTimeout(toast.t); toast.t = setTimeout(function () { t.classList.remove('on'); }, link ? 5000 : 2600);
  }
  function needAuth(what) { if (cfg.auth) return false; toast('Sign in to ' + what + '.', { href: cfg.login, text: 'Sign in' }); return true; }
  function fail(e) { toast(e && e.message ? e.message : 'Something went wrong.'); }

  // ── rendering ──────────────────────────────────────────────────────────────
  function ava(a, cls) {
    return a.official ? '<span class="fd-ava off ' + (cls || '') + '">' + ic('book') + '</span>'
      : '<span class="fd-ava ' + (cls || '') + '" style="background:hsl(' + a.hue + ' 70% 88%)">' + esc(a.emoji) + '</span>';
  }
  function who(a) { return '<span class="fd-name">' + esc(a.name) + '</span>' + (a.official ? '<span class="fd-ver" title="Official account">' + ic('check') + '</span>' : ''); }
  function mediaHTML(p) {
    var m = p.media || [], i, h = '';
    if (!m.length) return '';
    if (p.kind === 'video') {
      var u = safeUrl(m[0].url);
      return '<div class="fd-media fd-vid"><video src="' + esc(u) + '#t=0.1" preload="metadata" playsinline muted loop></video>' +
        '<button class="fd-mute" data-act="mute" aria-label="Sound">' + ic('mute') + '</button></div>';
    }
    if (m.length === 1) return '<div class="fd-media"><img src="' + esc(safeUrl(m[0].url)) + '" alt="" loading="lazy" decoding="async" data-i="0"' + (m[0].w ? ' width="' + m[0].w + '" height="' + m[0].h + '"' : '') + '></div>';
    for (i = 0; i < m.length; i++) h += '<img src="' + esc(safeUrl(m[i].url)) + '" alt="" loading="lazy" decoding="async" data-i="' + i + '">';
    return '<div class="fd-media fd-car"><div class="fd-track">' + h + '</div><span class="fd-cnt">1/' + m.length + '</span><div class="fd-dots">' +
      m.map(function (_, k) { return '<i' + (k ? '' : ' class="on"') + '></i>'; }).join('') + '</div></div>';
  }
  function actions(p) {
    return '<div class="fd-acts"><button class="fd-act js-like' + (p.liked ? ' on' : '') + '" data-act="like" aria-label="Like" aria-pressed="' + !!p.liked + '">' + ic('heart') + '</button>' +
      '<button class="fd-act" data-act="comment" aria-label="Comments">' + ic('comment') + '</button>' +
      '<button class="fd-act" data-act="share" aria-label="Share">' + ic('share') + '</button>' +
      '<button class="fd-act right js-save' + (p.saved ? ' on' : '') + '" data-act="save" aria-label="Save">' + ic('save') + '</button></div>';
  }
  function statsText(p) {
    var s = [];
    s.push('<b class="js-likes">' + num(p.likes) + '</b> like' + (p.likes === 1 ? '' : 's'));
    if (p.views && p.kind === 'video') s.push(num(p.views) + ' view' + (p.views === 1 ? '' : 's'));
    return s.join(' · ');
  }
  function postHTML(p) {
    var long = (p.body || '').length > 280;
    return '<article class="fd-post" data-id="' + p.id + '"><header class="fd-ph">' + ava(p.author) +
      '<div class="fd-who">' + who(p.author) + '<span class="fd-time" title="' + esc(new Date(p.created).toLocaleString()) + '">' + ago(p.created) + (p.pinned ? ' · <span class="fd-pin">' + ic('pin') + ' Pinned</span>' : '') + '</span></div>' +
      '<button class="fd-act" data-act="menu" aria-label="More options">' + ic('more') + '</button></header>' +
      (p.body ? '<p class="fd-text' + (long ? ' clamp' : '') + '">' + rich(p.body) + '</p>' + (long ? '<button class="fd-more" data-act="more">more</button>' : '') : '') +
      mediaHTML(p) + actions(p) + '<div class="fd-stats">' + statsText(p) + '</div>' +
      '<button class="fd-viewc js-cc" data-act="comment">' + cmtLabel(p) + '</button><div class="fd-cmts" hidden></div></article>';
  }
  function cmtLabel(p) { return p.comments ? 'View all ' + num(p.comments) + ' comment' + (p.comments === 1 ? '' : 's') : 'Add a comment'; }
  function reelHTML(p) {
    return '<section class="fd-reel" data-id="' + p.id + '"><video src="' + esc(safeUrl((p.media[0] || {}).url)) + '" preload="metadata" playsinline muted loop></video>' +
      '<div class="fd-shade"></div><div class="fd-rinfo"><div class="fd-rwho">' + ava(p.author, 'sm') + who(p.author) + '</div>' +
      (p.body ? '<p class="fd-rtext">' + rich(p.body) + '</p>' : '') + '</div><div class="fd-rail">' +
      '<button class="fd-ract js-like' + (p.liked ? ' on' : '') + '" data-act="like" aria-label="Like">' + ic('heart') + '<span class="js-likes">' + num(p.likes) + '</span></button>' +
      '<button class="fd-ract" data-act="comment" aria-label="Comments">' + ic('comment') + '<span class="js-cn">' + num(p.comments) + '</span></button>' +
      '<button class="fd-ract" data-act="share" aria-label="Share">' + ic('share') + '<span>Share</span></button>' +
      '<button class="fd-ract js-save' + (p.saved ? ' on' : '') + '" data-act="save" aria-label="Save">' + ic('save') + '<span>Save</span></button>' +
      '<button class="fd-ract" data-act="mute" aria-label="Sound">' + ic('mute') + '</button>' +
      '<button class="fd-ract" data-act="menu" aria-label="More options">' + ic('more') + '</button></div></section>';
  }
  function skeleton() { return '<div class="fd-post sk"><div class="fd-ph"><span class="fd-ava"></span><div class="fd-who"><i class="sk-l w40"></i><i class="sk-l w20"></i></div></div><i class="sk-l w90"></i><i class="sk-b"></i></div>'; }
  function empty() {
    var m = { feed: ['No updates yet', 'Be the first to share something.'], reels: ['No videos yet', 'Short videos will show up here.'], saved: ['Nothing saved yet', 'Tap the bookmark on a post to keep it here.'] }[tab];
    if (tab === 'saved' && !cfg.auth) return '<div class="fd-empty"><h3>Sign in to see saved posts</h3><a class="btn accent" href="' + esc(cfg.login) + '">Sign in</a></div>';
    return '<div class="fd-empty"><h3>' + m[0] + '</h3><p>' + m[1] + '</p></div>';
  }

  // ── loading ────────────────────────────────────────────────────────────────
  function target() { return tab === 'reels' ? reels : list; }
  function load(first) {
    if (loading || done) return;
    loading = true; var my = gen;
    if (first) target().innerHTML = tab === 'reels' ? '' : skeleton() + skeleton();
    if (tab === 'saved' && !cfg.auth) { target().innerHTML = empty(); loading = false; done = true; return; }
    var url = '/api/feed?tab=' + tab + '&limit=' + (tab === 'reels' ? 6 : 8) + (next ? '&before=' + next : '') + (cfg.tag ? '&tag=' + encodeURIComponent(cfg.tag) : '');
    api(url).then(function (d) {
      if (my !== gen) return;
      if (first) target().innerHTML = '';
      d.posts.forEach(function (p) { posts[p.id] = p; target().insertAdjacentHTML('beforeend', tab === 'reels' ? reelHTML(p) : postHTML(p)); });
      next = d.next; done = !d.next; loading = false;
      if (first && !d.posts.length) target().innerHTML = empty();
      watch(); sentinel.hidden = done;
    }).catch(function (e) { if (my !== gen) return; loading = false; if (first) target().innerHTML = '<div class="fd-empty"><h3>Couldn\'t load updates</h3><button class="btn ghost" data-act="retry">Try again</button></div>'; fail(e); });
  }
  function reset() { gen++; next = null; done = false; loading = false; posts = {}; list.innerHTML = ''; reels.innerHTML = ''; sentinel.hidden = false; load(true); }
  function setTab(t) {
    tab = t; history.replaceState(null, '', location.pathname + location.search + (t === 'feed' ? '' : '#' + t));
    qa('[data-tab]').forEach(function (b) { b.classList.toggle('on', b.dataset.tab === t); b.setAttribute('aria-selected', b.dataset.tab === t); });
    root.classList.toggle('reels-on', t === 'reels'); list.hidden = t === 'reels'; reels.hidden = t !== 'reels'; reset();
  }
  var io, vio;
  function watch() {
    if (!('IntersectionObserver' in window)) return;
    if (!io) io = new IntersectionObserver(function (es) { if (es[0].isIntersecting) load(false); }, { rootMargin: '700px' });
    io.disconnect(); io.observe(sentinel);
    if (!vio) vio = new IntersectionObserver(function (es) {
      es.forEach(function (e) {
        var v = e.target;
        if (e.isIntersecting && e.intersectionRatio >= 0.6 && !document.prerendering) { var pr = v.play(); if (pr && pr.catch) pr.catch(function () {}); countView(v); }
        else v.pause();
      });
    }, { threshold: [0, 0.6, 1] });
    qa('video').forEach(function (v) { if (!v.dataset.w) { v.dataset.w = 1; vio.observe(v); } });
  }
  function countView(v) {
    var id = v.closest('[data-id]').dataset.id, k = 'fv' + id;
    try { if (sessionStorage.getItem(k)) return; sessionStorage.setItem(k, 1); } catch (e) {}
    api('/api/feed/posts/' + id + '/view', { method: 'POST' }).catch(function () {});
  }

  // ── post actions ───────────────────────────────────────────────────────────
  function sync(id) {
    var p = posts[id]; if (!p) return;
    qa('[data-id="' + id + '"]').forEach(function (el) {
      var l = q('.js-like', el), s = q('.js-save', el), st = q('.fd-stats', el), cc = q('.js-cc', el), cn = q('.js-cn', el);
      if (l) { l.classList.toggle('on', !!p.liked); l.setAttribute('aria-pressed', !!p.liked); }
      if (s) s.classList.toggle('on', !!p.saved);
      if (st) st.innerHTML = statsText(p);
      if (cc) cc.textContent = cmtLabel(p);
      if (cn) cn.textContent = num(p.comments);
      qa('.js-likes', el).forEach(function (n) { if (!st) n.textContent = num(p.likes); });
    });
  }
  function like(id, burstEl) {
    if (needAuth('like posts')) return; var p = posts[id]; if (!p) return;
    if (burstEl) burst(burstEl);
    p.liked = !p.liked; p.likes += p.liked ? 1 : -1; sync(id);
    api('/api/feed/posts/' + id + '/like', { method: 'POST' }).then(function (d) { p.liked = d.liked; p.likes = d.likes; sync(id); })
      .catch(function (e) { p.liked = !p.liked; p.likes += p.liked ? 1 : -1; sync(id); fail(e); });
  }
  function burst(el) {
    var h = document.createElement('span'); h.className = 'fd-burst'; h.innerHTML = ic('heart'); el.appendChild(h); setTimeout(function () { h.remove(); }, 800);
  }
  function save(id) {
    if (needAuth('save posts')) return; var p = posts[id];
    p.saved = !p.saved; sync(id);
    api('/api/feed/posts/' + id + '/save', { method: 'POST' }).then(function (d) { p.saved = d.saved; sync(id); toast(d.saved ? 'Saved' : 'Removed from saved'); if (tab === 'saved' && !d.saved) removeEl(id); })
      .catch(function (e) { p.saved = !p.saved; sync(id); fail(e); });
  }
  function share(id) {
    var url = location.origin + '/updates?post=' + id;
    if (navigator.share) { navigator.share({ title: 'Smart Study Guides', url: url }).catch(function () {}); return; }
    (navigator.clipboard ? navigator.clipboard.writeText(url) : Promise.reject()).then(function () { toast('Link copied'); }, function () { toast(url); });
  }
  function removeEl(id) { qa('[data-id="' + id + '"]').forEach(function (e) { e.remove(); }); delete posts[id]; if (!target().children.length) target().innerHTML = empty(); }
  function del(id) {
    if (!confirm('Delete this post?')) return;
    api('/api/feed/posts/' + id, { method: 'DELETE' }).then(function () { removeEl(id); toast('Post deleted'); }).catch(fail);
  }
  function report(kind, id) {
    if (needAuth('report content')) return;
    var anchor = report.anchor;
    menu(anchor, [['Spam', 'spam'], ['Harassment or bullying', 'harassment'], ['Inappropriate content', 'inappropriate'], ['False information', 'false'], ['Something else', 'other']].map(function (r) {
      return { label: r[0], fn: function () { api('/api/feed/' + (kind === 'post' ? 'posts/' : 'comments/') + id + '/report', { method: 'POST', json: { reason: r[1] } }).then(function () { toast('Thanks. We\'ll take a look.'); }).catch(fail); } };
    }), 'Report');
  }
  function menu(btn, items, title) {
    var m = q('#fd-menu'); report.anchor = btn;
    m.innerHTML = (title ? '<div class="fd-mt">' + esc(title) + '</div>' : '') + items.map(function (it, i) { return '<button data-mi="' + i + '"' + (it.danger ? ' class="danger"' : '') + '>' + esc(it.label) + '</button>'; }).join('');
    m.hidden = false; var r = btn.getBoundingClientRect(), w = m.offsetWidth || 200;
    m.style.top = (r.bottom + window.scrollY + 6) + 'px'; m.style.left = Math.max(8, Math.min(window.innerWidth - w - 8, r.right + window.scrollX - w)) + 'px';
    m._items = items; setTimeout(function () { document.addEventListener('click', closeMenu, { once: true }); }, 0);
  }
  function closeMenu() { q('#fd-menu').hidden = true; }
  function postMenu(btn, id) {
    var p = posts[id], items = [{ label: p.saved ? 'Unsave' : 'Save', fn: function () { save(id); } }, { label: 'Copy link', fn: function () { share(id); } }];
    if (cfg.admin) items.push({ label: p.pinned ? 'Unpin from top' : 'Pin to top', fn: function () { api('/api/feed/posts/' + id + '/pin', { method: 'POST' }).then(function (d) { toast(d.pinned ? 'Pinned' : 'Unpinned'); reset(); }).catch(fail); } });
    if (!p.mine) items.push({ label: 'Report', fn: function () { setTimeout(function () { report('post', id); }, 0); } });
    if (p.can_remove) items.push({ label: 'Delete', danger: true, fn: function () { del(id); } });
    menu(btn, items);
  }

  // ── comments ───────────────────────────────────────────────────────────────
  function cHTML(c, reply) {
    return '<div class="fd-c' + (reply ? ' rep' : '') + '" data-cid="' + c.id + '" data-rm="' + (c.can_remove ? 1 : 0) + '" data-mine="' + (c.mine ? 1 : 0) + '">' + ava(c.author, 'sm') + '<div class="fd-cb"><div class="fd-cbub"><span class="fd-cn">' + who(c.author) +
      (c.is_op ? '<span class="fd-op">Author</span>' : '') + '</span> ' + rich(c.body) + '</div><div class="fd-cm"><span>' + ago(c.created) + '</span>' +
      '<button data-act="clike" class="' + (c.liked ? 'on' : '') + '"><b>' + (c.likes || '') + '</b> ' + (c.liked ? 'Liked' : 'Like') + '</button>' +
      '<button data-act="reply" data-name="' + esc(c.author.name) + '">Reply</button><button data-act="cmenu" aria-label="More">' + ic('more') + '</button></div>' +
      (c.replies && c.replies.length ? '<div class="fd-reps">' + c.replies.map(function (r) { return cHTML(r, true); }).join('') + '</div>' : '<div class="fd-reps"></div>') + '</div></div>';
  }
  function openComments(id, host) {
    var box = host || q('[data-id="' + id + '"] .fd-cmts');
    if (!box.hidden && !host) { box.hidden = true; return; }
    box.hidden = false; box.dataset.pid = id;
    box.innerHTML = '<div class="fd-clist"></div><button class="fd-more" data-act="cmore" hidden>View more comments</button>' +
      '<form class="fd-cform"><span class="fd-ava sm mask">' + ic('ghost') + '</span><input maxlength="500" placeholder="' + (cfg.auth ? 'Add a comment as Anonymous…' : 'Sign in to comment') + '" aria-label="Comment"' + (cfg.auth ? '' : ' readonly') + '><button type="submit">Post</button></form>';
    loadComments(box, 0);
    if (!cfg.auth) q('.fd-cform input', box).addEventListener('focus', function () { needAuth('comment'); });
  }
  function loadComments(box, after) {
    var id = box.dataset.pid, list_ = q('.fd-clist', box), more = q('[data-act="cmore"]', box);
    if (!after) list_.innerHTML = '<div class="sk-l w60"></div>';
    api('/api/feed/posts/' + id + '/comments' + (after ? '?after=' + after : '')).then(function (d) {
      if (!after) list_.innerHTML = '';
      d.comments.forEach(function (c) { list_.insertAdjacentHTML('beforeend', cHTML(c)); });
      more.hidden = !d.next; more.dataset.after = d.next || '';
      if (!after && !d.comments.length) list_.innerHTML = '<p class="fd-none">No comments yet. Start the conversation.</p>';
    }).catch(fail);
  }
  function submitComment(form) {
    if (needAuth('comment')) return;
    var box = form.closest('.fd-cmts'), input = q('input', form), body = input.value.trim(), id = box.dataset.pid;
    if (!body) return; input.disabled = true;
    api('/api/feed/posts/' + id + '/comments', { method: 'POST', json: { body: body, parent_id: form.dataset.parent || null } }).then(function (d) {
      input.value = ''; input.disabled = false; var none = q('.fd-none', box); if (none) none.remove();
      if (form.dataset.parent) { var par = q('[data-cid="' + form.dataset.parent + '"] .fd-reps', box); par.insertAdjacentHTML('beforeend', cHTML(d.comment, true)); }
      else q('.fd-clist', box).insertAdjacentHTML('beforeend', cHTML(d.comment));
      cancelReply(form); posts[id].comments = d.comments; sync(id);
    }).catch(function (e) { input.disabled = false; fail(e); });
  }
  function cancelReply(form) { delete form.dataset.parent; q('input', form).placeholder = 'Add a comment as Anonymous…'; var c = q('.fd-rc', form); if (c) c.remove(); }

  // ── composer ───────────────────────────────────────────────────────────────
  var files = [];
  function openCompose() {
    if (needAuth('post an update')) return; if (!cfg.canPost) { toast('Posting is turned off for your account.'); return; }
    q('#fd-modal').hidden = false; document.body.classList.add('fd-lock'); q('#fd-body').focus();
  }
  function closeCompose() { q('#fd-modal').hidden = true; document.body.classList.remove('fd-lock'); }
  function renderPreviews() {
    q('#fd-prev').innerHTML = files.map(function (f, i) {
      var u = URL.createObjectURL(f);
      return '<div class="fd-pv">' + (f.type.indexOf('video') === 0 ? '<video src="' + u + '" muted playsinline></video>' : '<img src="' + u + '" alt="">') + '<button type="button" data-act="rmfile" data-i="' + i + '" aria-label="Remove">' + ic('x') + '</button></div>';
    }).join('');
    updatePost();
  }
  function updatePost() { var n = q('#fd-body').value.trim().length; q('#fd-count').textContent = q('#fd-body').value.length + '/2000'; q('#fd-post').disabled = !(n || files.length); }
  var SMALL_VIDEO = 3.5 * 1048576, MAX_BODY = 3.9 * 1048576;   // the host rejects request bodies over ~4.5 MB
  function isVid(f) { return f.type.indexOf('video') === 0; }
  function shrink(f) {            // resize + re-encode photos in the browser so they stay small (also drops hidden metadata)
    return new Promise(function (res) {
      if (f.type === 'image/gif' || !window.createImageBitmap) return res(f);
      createImageBitmap(f).then(function (bmp) {
        var k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height)), c = document.createElement('canvas'), name = (f.name || 'photo').replace(/\.\w+$/, '');
        c.width = Math.max(1, Math.round(bmp.width * k)); c.height = Math.max(1, Math.round(bmp.height * k));
        c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
        c.toBlob(function (b) {
          if (b && b.type === 'image/webp') return res(new File([b], name + '.webp', { type: b.type }));
          c.toBlob(function (j) { res(j && j.size < f.size ? new File([j], name + '.jpg', { type: 'image/jpeg' }) : f); }, 'image/jpeg', 0.82);
        }, 'image/webp', 0.82);
      }).catch(function () { res(f); });
    });
  }
  function addFiles(fl) {
    var err = q('#fd-err'), jobs = []; err.textContent = '';
    Array.prototype.forEach.call(fl, function (f) {
      var vid = isVid(f), img = f.type.indexOf('image') === 0;
      if (!vid && !img) { err.textContent = 'Only photos and videos can be added.'; return; }
      if (f.size > 25 * 1048576) { err.textContent = vid ? 'Videos can be up to 25 MB.' : 'That photo is too large.'; return; }
      if ((vid && (files.length || jobs.length)) || files.some(isVid)) { err.textContent = 'Add either up to 4 photos or one video.'; return; }
      if (img && files.length + jobs.length >= 4) { err.textContent = 'You can add up to 4 photos.'; return; }
      jobs.push(vid ? Promise.resolve(f) : shrink(f));
    });
    Promise.all(jobs).then(function (done) {
      var before = files.length; done.forEach(function (f) { files.push(f); });
      if (!files.some(isVid) && files.reduce(function (n, f) { return n + f.size; }, 0) > MAX_BODY) { files.length = before; err.textContent = 'Those photos are too large together. Try fewer or smaller photos.'; }
      renderPreviews();
    });
  }
  function directUpload(file, bar) {   // big videos go straight to storage, not through the server
    return api('/api/feed/video-upload', { method: 'POST', json: { type: file.type || 'video/mp4', size: file.size } }).then(function (d) {
      return new Promise(function (res, rej) {
        var x = new XMLHttpRequest(); x.open('PUT', d.upload_url); x.setRequestHeader('Content-Type', d.content_type);
        x.upload.onprogress = function (e) { if (e.lengthComputable) bar(Math.round(e.loaded / e.total * 100)); };
        x.onload = function () { (x.status >= 200 && x.status < 300) ? res(d.key) : rej(new Error('The video upload failed. Please try again.')); };
        x.onerror = function () { rej(new Error('Couldn\'t upload the video. Check your connection and try again.')); };
        x.send(file);
      });
    });
  }
  function submitPost() {
    var btn = q('#fd-post'), err = q('#fd-err'), vid = files.filter(isVid)[0];
    btn.disabled = true; btn.classList.add('busy'); err.textContent = '';
    function bar(n) { btn.style.setProperty('--p', n + '%'); }
    function stop(msg) { btn.classList.remove('busy'); btn.style.removeProperty('--p'); btn.disabled = false; err.textContent = msg; }
    (vid && vid.size > SMALL_VIDEO ? directUpload(vid, bar) : Promise.resolve(null)).then(function (key) {
      var fd = new FormData(), x = new XMLHttpRequest();
      fd.append('body', q('#fd-body').value.trim());
      if (key) fd.append('video_key', key); else files.forEach(function (f) { fd.append('files', f); });
      x.open('POST', '/api/feed/posts'); x.setRequestHeader('X-Requested-With', 'ssg-feed'); x.withCredentials = true;
      x.upload.onprogress = function (e) { if (!key && e.lengthComputable) bar(Math.round(e.loaded / e.total * 100)); };
      x.onload = function () {
        var d = {}; try { d = JSON.parse(x.responseText); } catch (e) {}
        if (x.status === 201) {
          btn.classList.remove('busy'); btn.style.removeProperty('--p');
          closeCompose(); q('#fd-body').value = ''; files = []; renderPreviews();
          posts[d.post.id] = d.post;
          if (tab === 'feed' && !cfg.tag) { (list.querySelector('.fd-empty') || {}).outerHTML = ''; list.insertAdjacentHTML('afterbegin', postHTML(d.post)); watch(); }
          toast('Posted'); window.scrollTo({ top: 0, behavior: 'smooth' });
        } else stop(x.status === 413 ? 'That upload is too large. Try smaller photos.' : (d.error || 'Couldn\'t post. Please try again.'));
      };
      x.onerror = function () { stop('Network problem. Please try again.'); };
      x.send(fd);
    }).catch(function (e) { stop(e.message || 'Couldn\'t upload the video. Please try again.'); });
  }

  // ── lightbox ───────────────────────────────────────────────────────────────
  var lb = { urls: [], i: 0 };
  function openLB(urls, i) { lb.urls = urls; lb.i = i; q('#fd-lb').hidden = false; document.body.classList.add('fd-lock'); showLB(); }
  function showLB() { q('#fd-lb-img').src = lb.urls[lb.i]; q('#fd-lb-n').textContent = lb.urls.length > 1 ? (lb.i + 1) + ' / ' + lb.urls.length : ''; qa('.fd-lb-nav').forEach(function (b) { b.hidden = lb.urls.length < 2; }); }
  function closeLB() { q('#fd-lb').hidden = true; document.body.classList.remove('fd-lock'); }
  function stepLB(d) { lb.i = (lb.i + d + lb.urls.length) % lb.urls.length; showLB(); }

  // ── events ─────────────────────────────────────────────────────────────────
  function tap(el, single, dbl) {
    var now = Date.now();
    if (lastTap.el === el && now - lastTap.t < 320) { clearTimeout(lastTap.timer); lastTap.el = null; dbl(); return; }
    lastTap.el = el; lastTap.t = now; lastTap.timer = setTimeout(function () { lastTap.el = null; single(); }, 320);
  }
  root.addEventListener('click', function (e) {
    var t = e.target, a = t.closest('[data-act]'), host = t.closest('[data-id]'), id = host && host.dataset.id;
    var media = t.closest('.fd-media, .fd-reel > video');
    if (t.closest('#fd-lb-img')) return;
    if (media && !a) {
      var el = media.closest('.fd-reel') || media, v = media.tagName === 'VIDEO' ? media : q('video', media);
      return tap(el, function () {
        if (v) { v.paused ? v.play() : v.pause(); } else if (t.tagName === 'IMG') { var imgs = qa('img', media).map(function (i) { return i.src; }); openLB(imgs, +t.dataset.i || 0); }
      }, function () { like(id, media.closest('.fd-reel') || media); });
    }
    if (!a) return;
    var act = a.dataset.act;
    if (act === 'like') like(id); else if (act === 'save') save(id); else if (act === 'share') share(id);
    else if (act === 'menu') { e.stopPropagation(); postMenu(a, id); }
    else if (act === 'comment') { if (host.classList.contains('fd-reel')) { var s = q('#fd-sheet'); s.hidden = false; openComments(id, q('#fd-sheet-body')); } else openComments(id); }
    else if (act === 'more') { host.querySelector('.fd-text').classList.remove('clamp'); a.remove(); }
    else if (act === 'mute') { var vv = q('video', host) || q('video', media || host); vv.muted = !vv.muted; qa('[data-act="mute"]', host).forEach(function (b) { b.innerHTML = ic(vv.muted ? 'mute' : 'vol'); }); }
    else if (act === 'tab') setTab(a.dataset.tab);
    else if (act === 'retry') reset();
    else if (act === 'compose') openCompose();
    else if (act === 'close') closeCompose();
    else if (act === 'rmfile') { files.splice(+a.dataset.i, 1); renderPreviews(); }
    else if (act === 'pickphoto') { var f = q('#fd-file'); f.accept = 'image/*'; f.click(); }
    else if (act === 'pickvideo') { var f2 = q('#fd-file'); f2.accept = 'video/*'; f2.click(); }
    else if (act === 'lbclose') closeLB(); else if (act === 'lbprev') stepLB(-1); else if (act === 'lbnext') stepLB(1);
    else if (act === 'sheetclose') { q('#fd-sheet').hidden = true; }
    else if (act === 'cmore') loadComments(a.closest('.fd-cmts'), +a.dataset.after);
    else if (act === 'reply') {
      if (needAuth('reply')) return; var form = q('.fd-cform', a.closest('.fd-cmts')), c = a.closest('.fd-c'), pid = c.classList.contains('rep') ? c.closest('.fd-c:not(.rep)').dataset.cid : c.dataset.cid;
      form.dataset.parent = pid; var inp = q('input', form); inp.placeholder = 'Reply to ' + a.dataset.name + '…'; inp.focus();
      if (!q('.fd-rc', form)) form.insertAdjacentHTML('afterbegin', '<button type="button" class="fd-rc" data-act="cancelreply">Cancel reply</button>');
    } else if (act === 'cancelreply') cancelReply(a.closest('form'));
    else if (act === 'clike') {
      if (needAuth('like comments')) return; var cid = a.closest('.fd-c').dataset.cid;
      api('/api/feed/comments/' + cid + '/like', { method: 'POST' }).then(function (d) { a.classList.toggle('on', d.liked); a.innerHTML = '<b>' + (d.likes || '') + '</b> ' + (d.liked ? 'Liked' : 'Like'); }).catch(fail);
    } else if (act === 'cmenu') {
      e.stopPropagation(); var ce = a.closest('.fd-c'), cid2 = ce.dataset.cid, box = ce.closest('.fd-cmts'), cp = posts[box.dataset.pid], items = [];
      if (ce.dataset.mine !== '1') items.push({ label: 'Report', fn: function () { setTimeout(function () { report('comment', cid2); }, 0); } });
      if (ce.dataset.rm === '1') items.push({ label: 'Delete', danger: true, fn: function () { api('/api/feed/comments/' + cid2, { method: 'DELETE' }).then(function (d) { ce.remove(); cp.comments = d.comments; sync(box.dataset.pid); }).catch(fail); } });
      menu(a, items);
    }
  });
  root.addEventListener('submit', function (e) { var f = e.target.closest('.fd-cform'); if (f) { e.preventDefault(); submitComment(f); } else if (e.target.id === 'fd-form') { e.preventDefault(); submitPost(); } });
  q('#fd-menu').addEventListener('click', function (e) { var b = e.target.closest('[data-mi]'); if (b) { var fn = q('#fd-menu')._items[+b.dataset.mi].fn; closeMenu(); fn(); } });
  q('#fd-body').addEventListener('input', function () { this.style.height = 'auto'; this.style.height = Math.min(this.scrollHeight, 260) + 'px'; updatePost(); });
  q('#fd-file').addEventListener('change', function () { addFiles(this.files); this.value = ''; });
  q('#fd-modal').addEventListener('click', function (e) { if (e.target === this) closeCompose(); });
  q('#fd-lb').addEventListener('click', function (e) { if (e.target === this) closeLB(); });
  q('#fd-sheet').addEventListener('click', function (e) { if (e.target === this) this.hidden = true; });
  document.addEventListener('keydown', function (e) {
    if (e.key === 'Escape') { closeLB(); closeCompose(); closeMenu(); q('#fd-sheet').hidden = true; }
    if (!q('#fd-lb').hidden) { if (e.key === 'ArrowLeft') stepLB(-1); if (e.key === 'ArrowRight') stepLB(1); }
    else if (tab === 'reels' && (e.key === 'ArrowDown' || e.key === 'ArrowUp') && !/INPUT|TEXTAREA/.test((document.activeElement || {}).tagName)) { e.preventDefault(); reels.scrollBy({ top: (e.key === 'ArrowDown' ? 1 : -1) * reels.clientHeight, behavior: 'smooth' }); }
  });
  root.addEventListener('scroll', function (e) {
    var tr = e.target; if (!tr.classList || !tr.classList.contains('fd-track')) return;
    var i = Math.round(tr.scrollLeft / tr.clientWidth), box = tr.parentNode; qa('.fd-dots i', box).forEach(function (d, k) { d.classList.toggle('on', k === i); }); q('.fd-cnt', box).textContent = (i + 1) + '/' + tr.children.length;
  }, true);
  var lx = 0; q('#fd-lb').addEventListener('touchstart', function (e) { lx = e.touches[0].clientX; }, { passive: true });
  q('#fd-lb').addEventListener('touchend', function (e) { var d = e.changedTouches[0].clientX - lx; if (Math.abs(d) > 50) stepLB(d < 0 ? 1 : -1); }, { passive: true });

  // ── start ──────────────────────────────────────────────────────────────────
  function start() {
    if (cfg.focus) {
      root.classList.add('single'); sentinel.hidden = true; list.innerHTML = skeleton();
      api('/api/feed/posts/' + cfg.focus).then(function (d) { posts[d.post.id] = d.post; list.innerHTML = postHTML(d.post); openComments(d.post.id); watch(); })
        .catch(function () { list.innerHTML = '<div class="fd-empty"><h3>This post isn\'t available</h3><a class="btn ghost" href="/updates">See all updates</a></div>'; });
      return;
    }
    setTab(tab);
  }
  start();
})();
