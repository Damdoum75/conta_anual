const API_URL = (typeof window !== 'undefined' && window.API_URL !== undefined) ? window.API_URL : 'http://localhost:8000';

const app = {
  data() {
    return {
      isAuthenticated: false,
      authMode: 'login',
      email: '',
      password: '',
      registerFullName: '',
      registerNie: '',
      showNewDeclaration: false,
      declarations: [],
      me: null,
      showOfferModal: false,
    };
  },

  computed: {
    pendingCount() {
      return this.declarations.filter(d => d.status === 'pending_payment').length;
    },
    validatedCount() {
      return this.declarations.filter(d => d.status === 'paid').length;
    }
  },

  methods: {
    authHeaders() {
      const token = localStorage.getItem('token');
      return token ? { 'Authorization': `Bearer ${token}` } : {};
    },

    async register() {
      try {
        const response = await fetch(`${API_URL}/api/auth/register`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({
            email: this.email,
            password: this.password,
            full_name: this.registerFullName || null,
            nie: this.registerNie || null,
          })
        });

        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          alert(err.detail || 'Erreur lors de l’inscription');
          return;
        }

        const data = await response.json();
        localStorage.setItem('token', data.access_token);
        this.isAuthenticated = true;
        await this.fetchMe();
        await this.fetchDeclarations();
        this.openOfferModal();
      } catch (error) {
        console.error('Register error:', error);
        alert('Erreur de connexion');
      }
    },

    async login() {
      try {
        const response = await fetch(`${API_URL}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: this.email, password: this.password })
        });

        if (!response.ok) {
          alert('Email ou mot de passe incorrect');
          return;
        }

        const data = await response.json();
        localStorage.setItem('token', data.access_token);
        this.isAuthenticated = true;
        await this.fetchMe();
        await this.fetchDeclarations();
        if (this.me && !this.me.has_access) {
          this.openOfferModal();
        }
      } catch (error) {
        console.error('Login error:', error);
        alert('Erreur de connexion');
      }
    },

    logout() {
      localStorage.removeItem('token');
      this.isAuthenticated = false;
      this.declarations = [];
      this.me = null;
      this.showOfferModal = false;
      this.email = '';
      this.password = '';
      this.registerFullName = '';
      this.registerNie = '';
      this.authMode = 'login';
    },

    openOfferModal() {
      this.showOfferModal = true;
    },

    async fetchMe() {
      const response = await fetch(`${API_URL}/api/users/me`, {
        headers: { ...this.authHeaders() }
      });
      if (response.ok) {
        this.me = await response.json();
      }
    },

    async startTrial() {
      try {
        const response = await fetch(`${API_URL}/api/billing/trial/start`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...this.authHeaders() },
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          alert(err.detail || 'Impossible de démarrer l’essai');
          return;
        }
        this.me = await response.json();
        this.showOfferModal = false;
      } catch (error) {
        console.error('Trial error:', error);
        alert('Erreur réseau');
      }
    },

    async startMonthlyAccess() {
      try {
        const response = await fetch(`${API_URL}/api/billing/monthly/checkout`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json', ...this.authHeaders() },
        });
        if (!response.ok) {
          const err = await response.json().catch(() => ({}));
          alert(err.detail || 'Impossible de créer le paiement');
          return;
        }
        const data = await response.json();
        if (data.checkout_url) {
          window.location.href = data.checkout_url;
        } else {
          alert('URL de paiement indisponible');
        }
      } catch (error) {
        console.error('Checkout error:', error);
        alert('Erreur réseau');
      }
    },

    async fetchDeclarations() {
      try {
        const response = await fetch(`${API_URL}/api/tax-returns/`, {
          headers: { ...this.authHeaders() }
        });

        if (response.ok) {
          this.declarations = await response.json();
        }
      } catch (error) {
        console.error('Fetch error:', error);
      }
    },

    viewDeclaration(decl) {
      alert(`Ouverture de la déclaration #${decl.id} (page détail à implémenter)`);
    },

    formatDate(date) {
      return new Date(date).toLocaleDateString('fr-FR');
    }
  },

  async mounted() {
    const token = localStorage.getItem('token');
    if (token) {
      this.isAuthenticated = true;
      await this.fetchMe();
      await this.fetchDeclarations();
    }

    const params = new URLSearchParams(window.location.search);
    const payment = params.get('payment');
    if (payment === 'success' && this.isAuthenticated) {
      await this.fetchMe();
    }
  }
};

if (typeof Vue !== 'undefined' && Vue.createApp) {
  Vue.createApp(app).mount('#app');
}
