(function () {
  'use strict';

  function isDark() {
    return document.documentElement.getAttribute('data-bs-theme') === 'dark';
  }

  var ND = {
    edge: 'rgba(79,216,242,.2)',
    pulse: 'rgba(180,240,255,.85)',
    hub: '255,43,214',
    hubGlow: '#ff2bd6',
    spec: '#39ff88',
    node: 'rgba(120,225,245,.85)',
    glow: 1
  };
  var NL = {
    edge: 'rgba(0,115,150,.26)',
    pulse: 'rgba(0,120,160,.9)',
    hub: '214,20,140',
    hubGlow: '#d6148c',
    spec: '#0fa968',
    node: 'rgba(0,140,175,.85)',
    glow: 0.3
  };

  function network(cv) {
    var ctx = cv.getContext('2d'), W = 0, H = 0,
        dpr = Math.min(window.devicePixelRatio || 1, 2),
        nodes = [], edges = [], mx = 0, my = 0, vis = true;

    function seed() {
      nodes = []; edges = [];
      var n = Math.max(36, Math.min(84, Math.round(W / 16))),
          hubs = 7, i;
      for (i = 0; i < n; i++) {
        var hub = i < hubs;
        nodes.push({
          x: Math.random() * W, y: Math.random() * H,
          bx: 0, by: 0, hub: hub, deg: 0,
          ph: Math.random() * 6.28,
          sp: 0.25 + Math.random() * 0.35,
          amp: 6 + Math.random() * 10,
          r: hub ? 5.5 : 2 + Math.random() * 1.6
        });
      }
      nodes.forEach(function (a) { a.bx = a.x; a.by = a.y; });
      for (i = hubs; i < n; i++) {
        var a = nodes[i], best = [], j;
        for (j = 0; j < n; j++) {
          if (j === i) continue;
          best.push([Math.hypot(a.bx - nodes[j].bx, a.by - nodes[j].by), j]);
        }
        best.sort(function (p, q) { return p[0] - q[0]; });
        var k = Math.random() < 0.45 ? 1 : 2, m;
        for (m = 0; m < k; m++) {
          var t = best[m][1];
          if (best[m][0] < W * 0.3) {
            edges.push([i, t, Math.random()]);
            a.deg++;
            nodes[t].deg++;
          }
        }
      }
      for (i = 0; i < hubs; i++) {
        for (var j2 = i + 1; j2 < hubs; j2++) {
          if (Math.hypot(nodes[i].bx - nodes[j2].bx, nodes[i].by - nodes[j2].by) < W * 0.4) {
            edges.push([i, j2, Math.random()]);
            nodes[i].deg++;
            nodes[j2].deg++;
          }
        }
      }
    }

    function size() {
      var rc = cv.getBoundingClientRect();
      if (!rc.width) return;
      W = rc.width; H = rc.height;
      cv.width = W * dpr; cv.height = H * dpr;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      seed();
    }

    function draw(t) {
      ctx.clearRect(0, 0, W, H);
      var NP = isDark() ? ND : NL;
      nodes.forEach(function (n) {
        n.x = n.bx + Math.sin(t * n.sp + n.ph) * n.amp + mx * (n.hub ? 14 : 8);
        n.y = n.by + Math.cos(t * n.sp * 0.8 + n.ph) * n.amp + my * (n.hub ? 14 : 8);
      });
      edges.forEach(function (e) {
        var a = nodes[e[0]], c = nodes[e[1]];
        ctx.strokeStyle = NP.edge;
        ctx.lineWidth = 1;
        ctx.beginPath();
        ctx.moveTo(a.x, a.y);
        ctx.lineTo(c.x, c.y);
        ctx.stroke();
        var p = ((t * 0.12 + e[2]) % 1);
        ctx.fillStyle = NP.pulse;
        ctx.beginPath();
        ctx.arc(a.x + (c.x - a.x) * p, a.y + (c.y - a.y) * p, 1.3, 0, 6.283);
        ctx.fill();
      });
      nodes.forEach(function (n) {
        if (n.hub) {
          var pu = 0.5 + 0.5 * Math.sin(t * 1.6 + n.ph);
          ctx.strokeStyle = 'rgba(' + NP.hub + ',' + (0.55 + 0.35 * pu) + ')';
          ctx.lineWidth = 2;
          ctx.shadowColor = NP.hubGlow;
          ctx.shadowBlur = 14 * NP.glow;
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r + pu * 1.5, 0, 6.283);
          ctx.stroke();
          ctx.shadowBlur = 0;
          ctx.fillStyle = 'rgba(' + NP.hub + ',.25)';
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r - 1, 0, 6.283);
          ctx.fill();
        } else if (n.deg <= 1) {
          ctx.fillStyle = NP.spec;
          ctx.shadowColor = NP.spec;
          ctx.shadowBlur = 12 * NP.glow;
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r + 0.6, 0, 6.283);
          ctx.fill();
          ctx.shadowBlur = 0;
        } else {
          ctx.fillStyle = NP.node;
          ctx.beginPath();
          ctx.arc(n.x, n.y, n.r, 0, 6.283);
          ctx.fill();
        }
      });
    }

    function loop(ts) {
      if (vis && !document.hidden && W) draw(ts / 1000);
      requestAnimationFrame(loop);
    }

    size();
    var reduce = window.matchMedia && matchMedia('(prefers-reduced-motion: reduce)').matches;
    if (reduce) {
      draw(2);
    } else {
      requestAnimationFrame(loop);
    }
    window.addEventListener('resize', function () { size(); if (reduce) draw(2); });
    cv.parentNode.addEventListener('pointermove', function (e) {
      var rc = cv.getBoundingClientRect();
      mx = ((e.clientX - rc.left) / rc.width - 0.5);
      my = ((e.clientY - rc.top) / rc.height - 0.5);
    });
    if ('IntersectionObserver' in window) {
      new IntersectionObserver(function (es) { vis = es[0].isIntersecting; }).observe(cv);
    }
  }

  function init() {
    document.querySelectorAll('.ks-hero canvas, .ks-loading-bg-net, .ks-loading-net, canvas.netc').forEach(function (cv) {
      if (!cv._ksInit) {
        cv._ksInit = true;
        network(cv);
      }
    });
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', init);
  } else {
    init();
  }
})();
