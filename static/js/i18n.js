// ── HASSAI Bridge — Internationalization ──

const TRANSLATIONS = {
  en: {
    // Tabs
    'tab.info': 'Info',
    'tab.conversations': 'Conversations',
    'tab.settings': 'Settings',
    'tab.users': 'Users',
    'tab.logs': 'Logs',

    // Info panel
    'info.serviceStatus': 'Service Status',
    'info.memoryAi': 'AI Memory',
    'info.checking': 'Checking...',
    'info.statistics': 'Statistics',
    'info.uptime': 'Uptime',
    'info.users': 'Users',
    'info.totalMemories': 'Total Memories',
    'info.messages': 'Messages',
    'info.actions24h': 'Actions (24h)',
    'info.haConnect': 'Home Assistant Connection',
    'info.haConnectDesc': 'Use the <strong>HASSAI Bridge</strong> integration from Home Assistant. Enter the URL and API Key below.',
    'info.baseUrl': 'Base URL (for integration)',
    'info.apiKey': 'API Key',
    'info.copy': 'Copy',
    'info.show': 'Show',
    'info.availableEndpoints': 'Available Endpoints',
    'info.loading': 'Loading...',
    'info.refresh': 'Refresh',
    'info.restartServer': 'Restart Server',

    // Conversations
    'conv.selectUser': 'Select User',
    'conv.user': 'User',
    'conv.choose': '— Choose —',
    'conv.reload': 'Reload',
    'conv.sessions': 'Conversation Sessions',
    'conv.conversation': 'Conversation',
    'conv.delete': 'Delete',
    'conv.noConversations': 'No conversations found for this user.',
    'conv.noMessages': 'No messages in this session.',
    'conv.messages': 'messages',
    'conv.loadingMessages': 'Loading...',

    // Settings
    'settings.serverUrl': 'Server URL',
    'settings.model': 'Model',
    'settings.reload': 'Reload',
    'settings.timeout': 'Timeout (seconds)',
    'settings.maxTokens': 'Max Tokens',
    'settings.temperature': 'Temperature',
    'settings.tempDesc': '(0.0 = deterministic, 1.0 = creative)',
    'settings.searxng': 'SearXNG — AI Web Search',
    'settings.searxngDesc': 'When enabled, the AI decides on its own when to search the internet, based on knowledge cutoff date.',
    'settings.searxngEnabled': 'Enabled — AI can search the internet',
    'settings.knowledgeCutoff': 'Knowledge Cutoff Date',
    'settings.knowledgeCutoffDesc': '(month up to which the AI has training data, e.g.: 2024-01)',
    'settings.searxngUrl': 'SearXNG Server URL',
    'settings.maxResults': 'Max results per search',
    'settings.maxChars': 'Max characters per page',
    'settings.cacheTtl': 'Cache TTL (seconds)',
    'settings.cacheTtlDesc': '(how long results stay cached)',
    'settings.memoryAi': 'AI Memory',
    'settings.memoryDesc': 'Automatic fact extraction from conversations, personalized responses per user.',
    'settings.memoryEnabled': 'Memory enabled',
    'settings.autoExtract': 'Auto-extract from conversations',
    'settings.maxMemories': 'Max memories per user',
    'settings.performance': 'Performance',
    'settings.perfDesc': 'Optimizations for faster response time.',
    'settings.historyLimit': 'Conversation history limit',
    'settings.historyLimitDesc': '(how many history messages to send to LLM)',
    'settings.parallelFetch': 'Fetch web pages in parallel',
    'settings.systemPrompt': 'System Prompt',
    'settings.backup': 'Backup / Restore',
    'settings.backupDesc': 'Download a copy of the database or restore from backup. Restoring replaces all existing data!',
    'settings.downloadBackup': 'Download Backup',
    'settings.restore': 'Restore',
    'settings.save': 'Save',
    'settings.checkConnection': 'Check Connection',
    'settings.language': 'Language',

    // Users
    'users.newUser': 'New User',
    'users.username': 'Username',
    'users.usernamePlaceholder': 'e.g.: maria',
    'users.generateKey': 'Generate API Key',
    'users.defaultUser': 'Default user:',
    'users.defaultUserPlaceholder': 'e.g.: andrei',
    'users.save': 'Save',
    'users.defaultUserDesc': 'Used when Home Assistant doesn\'t send user information.',
    'users.noUsers': 'No users configured. Add one above.',
    'users.copy': 'Copy',
    'users.delete': 'Delete',
    'users.noKey': 'no API key',

    // User modal
    'modal.memoriesConfig': 'Memories and user configuration',
    'modal.addMemory': 'Add Memory',
    'modal.category': 'Category',
    'modal.importance': 'Importance (1-5)',
    'modal.content': 'Content',
    'modal.contentPlaceholder': 'E.g.: Prefers answers in Romanian...',
    'modal.keywords': 'Keywords (comma)',
    'modal.keywordsPlaceholder': 'language, romanian, preference',
    'modal.add': 'Add',
    'modal.memoryList': 'Memory List',
    'modal.filterAll': 'All',
    'modal.filterPersonal': 'Personal',
    'modal.filterPreferences': 'Preferences',
    'modal.filterHome': 'Home',
    'modal.filterFacts': 'Facts',
    'modal.filterInstructions': 'Instructions',
    'modal.filterContext': 'Context',
    'modal.consolidate': 'AI Consolidation',
    'modal.deleteAll': 'Delete All',
    'modal.deleteUser': 'Delete User',
    'modal.total': 'Total',

    // Categories
    'cat.personal_info': 'Personal Info',
    'cat.preferences': 'Preferences',
    'cat.home_setup': 'Home Setup',
    'cat.facts': 'Facts',
    'cat.instructions': 'Instructions',
    'cat.context': 'Context',

    // Status strings
    'status.connected': 'Connected',
    'status.unavailable': 'Unavailable',
    'status.disabled': 'Disabled',
    'status.active': 'Active',
    'status.activeAutoExtract': 'Active + Auto-extract',
    'status.memoriesStored': '{count} memories stored',
    'status.userRole': 'User',
    'status.assistantRole': 'Assistant',
    'status.noMemory': 'No memories.',
    'status.accessed': 'accessed {count}x',
    'status.notAccessed': 'not accessed',

    // Toast messages
    'toast.copied': 'Copied!',
    'toast.copyFail': 'Could not copy',
    'toast.infoRefreshed': 'Info refreshed!',
    'toast.infoError': 'Error loading info: {msg}',
    'toast.modelsReloaded': 'Models reloaded!',
    'toast.loadModelsFail': 'Could not load models: {msg}',
    'toast.settingsSaved': 'Settings saved!',
    'toast.settingsError': 'Error loading settings: {msg}',
    'toast.error': 'Error: {msg}',
    'toast.usersReloaded': 'Users reloaded!',
    'toast.usersError': 'Error loading users: {msg}',
    'toast.userCreated': 'User "{name}" created!',
    'toast.userExists': 'User already exists',
    'toast.userDeleted': 'User "{name}" fully deleted',
    'toast.enterUsername': 'Enter a username',
    'toast.defaultUserSaved': 'Default user saved!',
    'toast.apiKeyCopied': 'API Key copied!',
    'toast.memoryAdded': 'Memory added!',
    'toast.memoryDeleted': 'Memory deleted',
    'toast.memoriesDeleted': 'Memories deleted',
    'toast.writeContent': 'Write the content',
    'toast.selectUser': 'Select a user',
    'toast.consolidating': 'Consolidating...',
    'toast.consolidateComplete': 'Consolidation complete!',
    'toast.serverRestarting': 'Server is restarting...',
    'toast.restartError': 'Error restarting: {msg}',
    'toast.backupDownloaded': 'Backup downloaded!',
    'toast.restoreError': 'Error restoring: {msg}',
    'toast.dbRestored': 'Database restored! Reloading...',
    'toast.convsError': 'Error loading conversations: {msg}',
    'toast.sessionDeleted': 'Conversation deleted!',
    'toast.langSaved': 'Language changed!',

    // Confirm dialogs
    'confirm.deleteUser': 'Delete user "{name}", API key and ALL associated memories?\n\nThis action is irreversible!',
    'confirm.restart': 'Are you sure you want to restart the HASSAI Bridge server?',
    'confirm.restore': 'Restoring replaces ALL existing data!\n\nAre you sure?',
    'confirm.deleteSession': 'Are you sure you want to delete this conversation?\n\nThis action is irreversible!',
    'confirm.deleteAllMemories': 'Delete ALL memories for "{name}"?',

    // Misc
    'misc.saved': '(saved)',
    'misc.defaultNoModel': 'default (no model detected)',
    'misc.defaultUnavailable': 'default (LMStudio unavailable)',
    'misc.close': 'Close',

    // Logs
    'logs.title': 'Server Logs',
    'logs.searchPlaceholder': 'Search...',
    'logs.autoRefresh': 'Auto-refresh',
    'logs.refresh': 'Refresh',
    'logs.clear': 'Clear',
    'logs.loading': 'Loading logs...',
    'logs.noLogs': 'No log entries.',
    'logs.loadError': 'Error loading logs: {msg}',
    'logs.cleared': 'View cleared. Click Refresh to reload.',
  },

  ro: {
    // Tabs
    'tab.info': 'Info',
    'tab.conversations': 'Conversații',
    'tab.settings': 'Setări',
    'tab.users': 'Utilizatori',
    'tab.logs': 'Loguri',

    // Info panel
    'info.serviceStatus': 'Status Servicii',
    'info.memoryAi': 'Memorie AI',
    'info.checking': 'Se verifică...',
    'info.statistics': 'Statistici',
    'info.uptime': 'Uptime',
    'info.users': 'Utilizatori',
    'info.totalMemories': 'Total Memorii',
    'info.messages': 'Mesaje',
    'info.actions24h': 'Acțiuni (24h)',
    'info.haConnect': 'Conectare Home Assistant',
    'info.haConnectDesc': 'Folosește integrarea <strong>HASSAI Bridge</strong> din Home Assistant. Introdu URL-ul și API Key-ul de mai jos.',
    'info.baseUrl': 'Base URL (pentru integrare)',
    'info.apiKey': 'API Key',
    'info.copy': 'Copiază',
    'info.show': 'Arată',
    'info.availableEndpoints': 'Endpointuri Disponibile',
    'info.loading': 'Se încarcă...',
    'info.refresh': 'Reîmprospătează',
    'info.restartServer': 'Restart Server',

    // Conversations
    'conv.selectUser': 'Selectează Utilizator',
    'conv.user': 'Utilizator',
    'conv.choose': '— Alege —',
    'conv.reload': 'Reîncarcă',
    'conv.sessions': 'Sesiuni de Conversație',
    'conv.conversation': 'Conversație',
    'conv.delete': 'Șterge',
    'conv.noConversations': 'Nicio conversație găsită pentru acest utilizator.',
    'conv.noMessages': 'Niciun mesaj în această sesiune.',
    'conv.messages': 'mesaje',
    'conv.loadingMessages': 'Se încarcă...',

    // Settings
    'settings.serverUrl': 'URL Server',
    'settings.model': 'Model',
    'settings.reload': 'Reîncarcă',
    'settings.timeout': 'Timeout (secunde)',
    'settings.maxTokens': 'Max Tokens',
    'settings.temperature': 'Temperatură',
    'settings.tempDesc': '(0.0 = deterministic, 1.0 = creativ)',
    'settings.searxng': 'SearXNG — Căutare Web AI',
    'settings.searxngDesc': 'Când este activat, AI-ul decide singur când trebuie să caute pe internet, bazat pe knowledge cutoff date.',
    'settings.searxngEnabled': 'Activat — AI poate căuta pe internet',
    'settings.knowledgeCutoff': 'Knowledge Cutoff Date',
    'settings.knowledgeCutoffDesc': '(luna până la care AI-ul are date de antrenament, ex: 2024-01)',
    'settings.searxngUrl': 'URL Server SearXNG',
    'settings.maxResults': 'Nr. maxim rezultate per căutare',
    'settings.maxChars': 'Caractere maxime per pagină',
    'settings.cacheTtl': 'Cache TTL (secunde)',
    'settings.cacheTtlDesc': '(cât timp rămân rezultatele în cache)',
    'settings.memoryAi': 'Memorie AI',
    'settings.memoryDesc': 'Extracție automată de fapte din conversații, personalizare răspunsuri per utilizator.',
    'settings.memoryEnabled': 'Memorie activată',
    'settings.autoExtract': 'Extracție automată din conversații',
    'settings.maxMemories': 'Memorii maxime per utilizator',
    'settings.performance': 'Performanță',
    'settings.perfDesc': 'Optimizări pentru timp de răspuns mai rapid.',
    'settings.historyLimit': 'Limită istoric conversații',
    'settings.historyLimitDesc': '(câte mesaje din istoric se trimit la LLM)',
    'settings.parallelFetch': 'Fetch pagini web în paralel',
    'settings.systemPrompt': 'System Prompt',
    'settings.backup': 'Backup / Restaurare',
    'settings.backupDesc': 'Descarcă o copie a bazei de date sau restaurează din backup. Restaurarea înlocuiește toate datele existente!',
    'settings.downloadBackup': 'Descarcă Backup',
    'settings.restore': 'Restaurează',
    'settings.save': 'Salvează',
    'settings.checkConnection': 'Verifică Conexiune',
    'settings.language': 'Limbă',

    // Users
    'users.newUser': 'Utilizator Nou',
    'users.username': 'Nume utilizator',
    'users.usernamePlaceholder': 'ex: maria',
    'users.generateKey': 'Generează API Key',
    'users.defaultUser': 'Utilizator implicit:',
    'users.defaultUserPlaceholder': 'ex: andrei',
    'users.save': 'Salvează',
    'users.defaultUserDesc': 'Folosit când Home Assistant nu trimite informații despre utilizator.',
    'users.noUsers': 'Niciun utilizator configurat. Adaugă unul mai sus.',
    'users.copy': 'Copiază',
    'users.delete': 'Șterge',
    'users.noKey': 'fără API key',

    // User modal
    'modal.memoriesConfig': 'Memorii și configurare utilizator',
    'modal.addMemory': 'Adaugă Memorie',
    'modal.category': 'Categorie',
    'modal.importance': 'Importanță (1-5)',
    'modal.content': 'Conținut',
    'modal.contentPlaceholder': 'Ex: Preferă răspunsuri în limba română...',
    'modal.keywords': 'Cuvinte cheie (virgulă)',
    'modal.keywordsPlaceholder': 'limbă, română, preferință',
    'modal.add': 'Adaugă',
    'modal.memoryList': 'Lista Memoriilor',
    'modal.filterAll': 'Toate',
    'modal.filterPersonal': 'Personal',
    'modal.filterPreferences': 'Preferințe',
    'modal.filterHome': 'Casă',
    'modal.filterFacts': 'Fapte',
    'modal.filterInstructions': 'Instrucțiuni',
    'modal.filterContext': 'Context',
    'modal.consolidate': 'Consolidare AI',
    'modal.deleteAll': 'Șterge Tot',
    'modal.deleteUser': 'Șterge Utilizator',
    'modal.total': 'Total',

    // Categories
    'cat.personal_info': 'Info Personal',
    'cat.preferences': 'Preferințe',
    'cat.home_setup': 'Configurare Casă',
    'cat.facts': 'Fapte',
    'cat.instructions': 'Instrucțiuni',
    'cat.context': 'Context',

    // Status strings
    'status.connected': 'Conectat',
    'status.unavailable': 'Indisponibil',
    'status.disabled': 'Dezactivat',
    'status.active': 'Activ',
    'status.activeAutoExtract': 'Activ + Auto-extracție',
    'status.memoriesStored': '{count} memorii stocate',
    'status.userRole': 'Utilizator',
    'status.assistantRole': 'Asistent',
    'status.noMemory': 'Nicio memorie.',
    'status.accessed': 'accesată de {count}x',
    'status.notAccessed': 'neaccesată',

    // Toast messages
    'toast.copied': 'Copiat!',
    'toast.copyFail': 'Nu s-a putut copia',
    'toast.infoRefreshed': 'Info reîmprospătat!',
    'toast.infoError': 'Eroare la încărcarea info: {msg}',
    'toast.modelsReloaded': 'Modele reîncărcate!',
    'toast.loadModelsFail': 'Nu s-au putut încărca modelele: {msg}',
    'toast.settingsSaved': 'Setări salvate!',
    'toast.settingsError': 'Eroare la încărcarea setărilor: {msg}',
    'toast.error': 'Eroare: {msg}',
    'toast.usersReloaded': 'Utilizatori reîncărcați!',
    'toast.usersError': 'Eroare la încărcarea utilizatorilor: {msg}',
    'toast.userCreated': 'Utilizator "{name}" creat!',
    'toast.userExists': 'Utilizatorul există deja',
    'toast.userDeleted': 'Utilizator "{name}" șters complet',
    'toast.enterUsername': 'Introdu un nume de utilizator',
    'toast.defaultUserSaved': 'Utilizator implicit salvat!',
    'toast.apiKeyCopied': 'API Key copiat!',
    'toast.memoryAdded': 'Memorie adăugată!',
    'toast.memoryDeleted': 'Memorie ștearsă',
    'toast.memoriesDeleted': 'Memorii șterse',
    'toast.writeContent': 'Scrie conținutul',
    'toast.selectUser': 'Selectează un utilizator',
    'toast.consolidating': 'Se consolidează...',
    'toast.consolidateComplete': 'Consolidare completă!',
    'toast.serverRestarting': 'Serverul se restartează...',
    'toast.restartError': 'Eroare la restart: {msg}',
    'toast.backupDownloaded': 'Backup descărcat!',
    'toast.restoreError': 'Eroare la restaurare: {msg}',
    'toast.dbRestored': 'Baza de date restaurată! Se reîncarcă...',
    'toast.convsError': 'Eroare la încărcarea conversațiilor: {msg}',
    'toast.sessionDeleted': 'Conversație ștearsă!',
    'toast.langSaved': 'Limbă schimbată!',

    // Confirm dialogs
    'confirm.deleteUser': 'Ștergi utilizatorul "{name}", API key-ul și TOATE memoriile asociate?\n\nAceastă acțiune este ireversibilă!',
    'confirm.restart': 'Ești sigur că vrei să restartezi serverul HASSAI Bridge?',
    'confirm.restore': 'Restaurarea înlocuiește TOATE datele existente!\n\nEști sigur?',
    'confirm.deleteSession': 'Ești sigur că vrei să ștergi această conversație?\n\nAceastă acțiune este ireversibilă!',
    'confirm.deleteAllMemories': 'Ștergi TOATE memoriile pentru "{name}"?',

    // Misc
    'misc.saved': '(salvat)',
    'misc.defaultNoModel': 'default (niciun model detectat)',
    'misc.defaultUnavailable': 'default (LMStudio indisponibil)',
    'misc.close': 'Închide',

    // Logs
    'logs.title': 'Loguri Server',
    'logs.searchPlaceholder': 'Caută...',
    'logs.autoRefresh': 'Auto-refresh',
    'logs.refresh': 'Reîmprospătează',
    'logs.clear': 'Curăță',
    'logs.loading': 'Se încarcă logurile...',
    'logs.noLogs': 'Nicio înregistrare în log.',
    'logs.loadError': 'Eroare la încărcarea logurilor: {msg}',
    'logs.cleared': 'Vizualizare curățată. Apasă Refresh pentru reîncărcare.',
  },
};

let currentLang = 'en';

/**
 * Get translated string. Supports {param} interpolation.
 * @param {string} key - Translation key
 * @param {Object} params - Interpolation params
 * @returns {string}
 */
function t(key, params = {}) {
  const lang = TRANSLATIONS[currentLang] || TRANSLATIONS.en;
  let str = lang[key] || TRANSLATIONS.en[key] || key;
  for (const [k, v] of Object.entries(params)) {
    str = str.replaceAll(`{${k}}`, v);
  }
  return str;
}

/**
 * Apply translations to all DOM elements with data-i18n attributes.
 */
function applyTranslations() {
  document.querySelectorAll('[data-i18n]').forEach(el => {
    el.textContent = t(el.dataset.i18n);
  });
  document.querySelectorAll('[data-i18n-html]').forEach(el => {
    el.innerHTML = t(el.dataset.i18nHtml);
  });
  document.querySelectorAll('[data-i18n-placeholder]').forEach(el => {
    el.placeholder = t(el.dataset.i18nPlaceholder);
  });
  document.querySelectorAll('[data-i18n-title]').forEach(el => {
    el.title = t(el.dataset.i18nTitle);
  });
  // Update html lang attribute
  document.documentElement.lang = currentLang;
}

/**
 * Set the active language, apply translations, and re-render dynamic content.
 */
function setLanguage(lang, skipSave) {
  if (!TRANSLATIONS[lang]) return;
  currentLang = lang;
  applyTranslations();
  // Update both language selectors
  const sel = document.getElementById('langSelect');
  if (sel) sel.value = lang;
  const selSettings = document.getElementById('settingsLang');
  if (selSettings) selSettings.value = lang;
  // Re-render dynamic content
  if (typeof loadSystemInfo === 'function') loadSystemInfo();
  if (typeof loadUsersTab === 'function') loadUsersTab();
  // Save to backend
  if (!skipSave) {
    if (typeof api === 'function') {
      api('PUT', '/api/settings/', { language: lang }).then(() => {
        toast(t('toast.langSaved'));
      }).catch(() => {});
    }
  }
}
