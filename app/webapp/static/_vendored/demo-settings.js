// The gallery's settings-group page: the gallery button and the home-head gear
// open it, its close shuts it, and the Language row opens a detail sheet long
// enough that its body scrolls between the pinned title and Done. Loaded as a
// module before the gallery's own script, so it is wired before demo-ready.
const page = document.getElementById('demoSettingsPage');
const sheet = document.getElementById('demoSettingsSheet');
const body = document.getElementById('demoSettingsSheetBody');

['English', 'Español', 'Français', 'Deutsch', 'Italiano', 'Português', 'Nederlands', 'Polski',
  'Svenska', 'Dansk', 'Norsk', 'Suomi', 'Čeština', 'Magyar', 'Română', 'Ελληνικά'].forEach((lang) => {
  const row = document.createElement('div');
  row.className = 'row';
  const name = document.createElement('span');
  name.textContent = lang;
  const state = document.createElement('span');
  state.textContent = lang === 'English' ? 'Selected' : '';
  row.append(name, state);
  body.append(row);
});

const openPage = () => page.showModal();
document.getElementById('openSettingsPage').addEventListener('click', openPage);
document.getElementById('demoHomeSettings').addEventListener('click', openPage);
document.getElementById('demoSettingsClose').addEventListener('click', () => page.close());
document.getElementById('demoSettingsLink').addEventListener('click', () => sheet.showModal());
document.getElementById('demoSettingsSheetClose').addEventListener('click', () => sheet.close());
document.getElementById('demoSettingsSheetDone').addEventListener('click', () => sheet.close());
