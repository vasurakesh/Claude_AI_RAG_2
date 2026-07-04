/* =========================================================
   KB Platform — Core JavaScript
   ========================================================= */

'use strict';

const KBPlatform = {

  /* ── Dark Mode ─────────────────────────────────────── */
  darkMode: {
    init() {
      const saved = localStorage.getItem('kb_theme') || 'light';
      this.apply(saved);
    },
    apply(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      document.body.classList.toggle('dark-mode', theme === 'dark');
      localStorage.setItem('kb_theme', theme);
      // Send preference to server so it persists across devices
      const url = document.body.dataset.themeUrl;
      if (url) {
        fetch(url, {
          method: 'POST',
          headers: {
            'X-CSRFToken': KBPlatform.utils.getCsrf(),
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ theme }),
        }).catch(() => {});
      }
    },
    toggle() {
      const current = localStorage.getItem('kb_theme') || 'light';
      this.apply(current === 'dark' ? 'light' : 'dark');
      // Update icon
      const icon = document.getElementById('darkModeIcon');
      if (icon) {
        icon.className = current === 'dark'
          ? 'fas fa-moon' : 'fas fa-sun';
      }
    },
  },

  /* ── CSRF helper ────────────────────────────────────── */
  utils: {
    getCsrf() {
      const el = document.querySelector('[name=csrfmiddlewaretoken]');
      if (el) return el.value;
      const cookie = document.cookie.split(';')
        .find(c => c.trim().startsWith('csrftoken='));
      return cookie ? cookie.split('=')[1] : '';
    },

    showToast(message, type = 'success') {
      // Uses AdminLTE toasts; falls back to alert
      if (typeof toastr !== 'undefined') {
        toastr[type](message);
      } else {
        alert(message);
      }
    },
  },

  /* ── AJAX form helper ───────────────────────────────── */
  forms: {
    bindAjax(formSelector, onSuccess) {
      document.querySelectorAll(formSelector).forEach(form => {
        form.addEventListener('submit', async e => {
          e.preventDefault();
          const btn = form.querySelector('[type=submit]');
          const originalText = btn ? btn.innerHTML : '';
          if (btn) {
            btn.disabled = true;
            btn.innerHTML = '<i class="fas fa-spinner fa-spin"></i> Please wait…';
          }
          try {
            const resp = await fetch(form.action || window.location.href, {
              method: form.method || 'POST',
              headers: { 'X-CSRFToken': KBPlatform.utils.getCsrf() },
              body: new FormData(form),
            });
            const data = await resp.json();
            if (onSuccess) onSuccess(data, form);
          } catch (err) {
            KBPlatform.utils.showToast('An error occurred. Please try again.', 'error');
          } finally {
            if (btn) { btn.disabled = false; btn.innerHTML = originalText; }
          }
        });
      });
    },
  },

  /* ── Login page parallax ────────────────────────────── */
  loginParallax: {
    init() {
      const page = document.querySelector('.login-page-kb');
      if (!page) return;
      document.addEventListener('mousemove', e => {
        const x = (e.clientX / window.innerWidth  - 0.5) * 20;
        const y = (e.clientY / window.innerHeight - 0.5) * 20;
        page.style.setProperty('--parallax-x', `${x}px`);
        page.style.setProperty('--parallax-y', `${y}px`);
        const orbs = page.querySelectorAll('.login-orb');
        orbs.forEach((orb, i) => {
          const factor = (i + 1) * 0.4;
          orb.style.transform = `translate(${x * factor}px, ${y * factor}px)`;
        });
      });
    },
  },

  /* ── Document upload drag-and-drop (wired in Phase 4) ─ */
  upload: {
    init(dropzoneId) {
      const zone = document.getElementById(dropzoneId);
      if (!zone) return;
      ['dragenter','dragover'].forEach(ev =>
        zone.addEventListener(ev, e => {
          e.preventDefault();
          zone.classList.add('dragover');
        })
      );
      ['dragleave','drop'].forEach(ev =>
        zone.addEventListener(ev, e => {
          e.preventDefault();
          zone.classList.remove('dragover');
        })
      );
      zone.addEventListener('drop', e => {
        const files = e.dataTransfer.files;
        if (files.length) KBPlatform.upload.handleFiles(files, zone);
      });
    },
    handleFiles(files, zone) {
      // Implemented in Phase 4 upload template
      console.log('Files ready:', files);
    },
  },

  /* ── Init ───────────────────────────────────────────── */
  init() {
    this.darkMode.init();
    this.loginParallax.init();
  },
};

document.addEventListener('DOMContentLoaded', () => KBPlatform.init());
