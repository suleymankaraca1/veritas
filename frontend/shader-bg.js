/**
 * VERİTAS — Soft Interactive Shader Background
 * Gentle flowing gradient, subtle mouse glow.
 * Usage: <canvas id="shaderBg"></canvas> then ShaderBG.init('shaderBg')
 */
window.ShaderBG = (function () {

  const VERT = `
    attribute vec2 a_pos;
    void main() { gl_Position = vec4(a_pos, 0.0, 1.0); }
  `;

  const FRAG = `
    precision mediump float;
    uniform float u_time;
    uniform vec2  u_res;
    uniform vec2  u_mouse;
    uniform float u_hover;

    vec3 mod289(vec3 x) { return x - floor(x / 289.0) * 289.0; }
    vec2 mod289(vec2 x) { return x - floor(x / 289.0) * 289.0; }
    vec3 permute(vec3 x) { return mod289((x * 34.0 + 1.0) * x); }

    float snoise(vec2 v) {
      const vec4 C = vec4(0.211324865405187, 0.366025403784439,
                         -0.577350269189626, 0.024390243902439);
      vec2 i = floor(v + dot(v, C.yy));
      vec2 x0 = v - i + dot(i, C.xx);
      vec2 i1 = (x0.x > x0.y) ? vec2(1.0, 0.0) : vec2(0.0, 1.0);
      vec4 x12 = x0.xyxy + C.xxzz;
      x12.xy -= i1;
      i = mod289(i);
      vec3 p = permute(permute(i.y + vec3(0.0, i1.y, 1.0))
                                   + i.x + vec3(0.0, i1.x, 1.0));
      vec3 m = max(0.5 - vec3(dot(x0,x0), dot(x12.xy,x12.xy),
                               dot(x12.zw,x12.zw)), 0.0);
      m = m * m; m = m * m;
      vec3 x = 2.0 * fract(p * C.www) - 1.0;
      vec3 h = abs(x) - 0.5;
      vec3 ox = floor(x + 0.5);
      vec3 a0 = x - ox;
      m *= 1.79284291400159 - 0.85373472095314 * (a0*a0 + h*h);
      vec3 g;
      g.x = a0.x * x0.x + h.x * x0.y;
      g.yz = a0.yz * x12.xz + h.yz * x12.yw;
      return 130.0 * dot(m, g);
    }

    float fbm(vec2 p) {
      float v = 0.0, a = 0.5;
      mat2 rot = mat2(cos(0.5), sin(0.5), -sin(0.5), cos(0.5));
      for (int i = 0; i < 4; i++) {
        v += a * snoise(p);
        p = rot * p * 2.0;
        a *= 0.5;
      }
      return v;
    }

    void main() {
      vec2 uv = gl_FragCoord.xy / u_res;
      vec2 p = (gl_FragCoord.xy - 0.5 * u_res) / min(u_res.x, u_res.y);
      float t = u_time * 0.05;

      float n1 = fbm(p * 1.8 + vec2(t, t * 0.7));
      float n2 = fbm(p * 1.3 - vec2(t * 0.4, t * 0.8) + n1 * 0.3);
      float n3 = fbm(p * 2.4 + vec2(n2 * 0.2, t * 0.3));

      vec3 base = vec3(0.957, 0.965, 0.969);
      vec3 soft = vec3(0.851, 0.925, 0.902);
      vec3 mid  = vec3(0.353, 0.608, 0.525);
      vec3 pale = vec3(0.930, 0.945, 0.940);

      float blend = n2 * 0.5 + 0.5;
      vec3 col = mix(base, pale, smoothstep(0.15, 0.85, blend) * 0.7);
      col = mix(col, soft, smoothstep(0.3, 0.7, n1 * 0.5 + 0.5) * 0.45);
      col = mix(col, mid, smoothstep(0.6, 0.9, n3 * 0.5 + 0.5) * 0.10);

      vec2 gp = p * 14.0 + vec2(n1 * 0.4, n2 * 0.4);
      float gx = abs(fract(gp.x) - 0.5);
      float gy = abs(fract(gp.y) - 0.5);
      float grid = smoothstep(0.48, 0.5, gx) + smoothstep(0.48, 0.5, gy);
      col = mix(col, mid, grid * 0.025);

      vec2 mUV = u_mouse / u_res;
      mUV.y = 1.0 - mUV.y;
      float md = distance(uv, mUV);
      float glow = exp(-md * md * 7.0) * u_hover;
      col = mix(col, soft, glow * 0.5);
      float warp = exp(-md * md * 5.0) * u_hover * 0.15;
      float nw = fbm(p * 2.5 + vec2(t * 1.5) + warp * 3.0);
      col = mix(col, mid, smoothstep(0.35, 0.8, nw * 0.5 + 0.5) * warp * 1.5);

      gl_FragColor = vec4(col, 1.0);
    }
  `;

  function init(canvasId) {
    const canvas = document.getElementById(canvasId);
    if (!canvas) return;
    const gl = canvas.getContext('webgl', { alpha: false, antialias: false });
    if (!gl) return;

    function compile(type, src) {
      const s = gl.createShader(type);
      gl.shaderSource(s, src);
      gl.compileShader(s);
      return s;
    }
    const prog = gl.createProgram();
    gl.attachShader(prog, compile(gl.VERTEX_SHADER, VERT));
    gl.attachShader(prog, compile(gl.FRAGMENT_SHADER, FRAG));
    gl.linkProgram(prog);
    gl.useProgram(prog);

    const buf = gl.createBuffer();
    gl.bindBuffer(gl.ARRAY_BUFFER, buf);
    gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1,-1, 1,-1, -1,1, 1,1]), gl.STATIC_DRAW);
    const aPos = gl.getAttribLocation(prog, 'a_pos');
    gl.enableVertexAttribArray(aPos);
    gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);

    const uTime  = gl.getUniformLocation(prog, 'u_time');
    const uRes   = gl.getUniformLocation(prog, 'u_res');
    const uMouse = gl.getUniformLocation(prog, 'u_mouse');
    const uHover = gl.getUniformLocation(prog, 'u_hover');

    let mx = 0, my = 0, hover = 0, hoverTarget = 0;
    const startTime = performance.now() / 1000;

    const mainEl = canvas.parentElement;
    mainEl.addEventListener('mousemove', e => {
      const r = canvas.getBoundingClientRect();
      mx = (e.clientX - r.left) * devicePixelRatio;
      my = (e.clientY - r.top) * devicePixelRatio;
      hoverTarget = 1;
    });
    mainEl.addEventListener('mouseleave', () => { hoverTarget = 0; });

    function resize() {
      const dpr = Math.min(devicePixelRatio || 1, 1.5);
      const w = mainEl.clientWidth;
      const h = mainEl.clientHeight;
      canvas.width = w * dpr;
      canvas.height = h * dpr;
      canvas.style.width = w + 'px';
      canvas.style.height = h + 'px';
      gl.viewport(0, 0, canvas.width, canvas.height);
    }
    resize();
    window.addEventListener('resize', resize);

    let lastFrame = 0;
    function frame(now) {
      requestAnimationFrame(frame);
      if (now - lastFrame < 32) return;
      lastFrame = now;

      const t = performance.now() / 1000 - startTime;
      hover += (hoverTarget - hover) * 0.04;

      gl.uniform1f(uTime, t);
      gl.uniform2f(uRes, canvas.width, canvas.height);
      gl.uniform2f(uMouse, mx, my);
      gl.uniform1f(uHover, hover);

      gl.drawArrays(gl.TRIANGLE_STRIP, 0, 4);
    }
    requestAnimationFrame(frame);
  }

  return { init: init };
})();
