document.querySelectorAll('form[data-confirmar]').forEach(form => {
  form.addEventListener('submit', evento => {
    if (!confirm(form.dataset.confirmar)) evento.preventDefault();
  });
});
