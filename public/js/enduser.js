(function () {
  const homeScreen = document.getElementById('homeScreen');
  const ticketScreen = document.getElementById('ticketScreen');
  const ticketCard = document.getElementById('ticketCard');
  const ticketKicker = document.getElementById('ticketKicker');
  const ticketNumber = document.getElementById('ticketNumber');
  const errorNote = document.getElementById('errorNote');
  const backBtn = document.getElementById('backBtn');

  let autoReturnTimer = null;

  document.querySelectorAll('.choice-card').forEach((btn) => {
    btn.addEventListener('click', () => requestTicket(btn.dataset.line));
  });

  backBtn.addEventListener('click', showHome);

  async function requestTicket(line) {
    errorNote.hidden = true;
    document.querySelectorAll('.choice-card').forEach((b) => (b.disabled = true));
    try {
      const res = await fetch('/api/ticket', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ line }),
      });
      const data = await res.json();
      if (!data.ok) throw new Error(data.error || 'Could not issue a ticket');
      showTicket(line, data.number);
    } catch (err) {
      errorNote.textContent = 'Something went wrong: ' + err.message + '. Please try again or ask staff for help.';
      errorNote.hidden = false;
    } finally {
      document.querySelectorAll('.choice-card').forEach((b) => (b.disabled = false));
    }
  }

  function showTicket(line, number) {
    ticketCard.classList.remove('registration', 'verification');
    ticketCard.classList.add(line);
    ticketKicker.textContent = line === 'verification' ? 'Verification / Update Number' : 'New Registration Number';
    ticketNumber.textContent = number;
    homeScreen.hidden = true;
    ticketScreen.hidden = false;

    clearTimeout(autoReturnTimer);
    autoReturnTimer = setTimeout(showHome, 15000);
  }

  function showHome() {
    clearTimeout(autoReturnTimer);
    ticketScreen.hidden = true;
    homeScreen.hidden = false;
  }
})();
