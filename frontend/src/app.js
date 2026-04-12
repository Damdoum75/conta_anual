const API_URL = 'http://localhost:8000';

const app = {
  data() {
    return {
      isAuthenticated: false,
      email: '',
      password: '',
      showNewDeclaration: false,
      declarations: []
    };
  },
  
  computed: {
    pendingCount() {
      return this.declarations.filter(d => d.status === 'pending').length;
    },
    validatedCount() {
      return this.declarations.filter(d => d.status === 'validated').length;
    }
  },
  
  methods: {
    async login() {
      try {
        const response = await fetch(`${API_URL}/api/auth/login`, {
          method: 'POST',
          headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ email: this.email, password: this.password })
        });
        
        if (response.ok) {
          const data = await response.json();
          localStorage.setItem('token', data.access_token);
          this.isAuthenticated = true;
          this.fetchDeclarations();
        } else {
          alert('Email ou mot de passe incorrect');
        }
      } catch (error) {
        console.error('Login error:', error);
        alert('Erreur de connexion');
      }
    },
    
    async fetchDeclarations() {
      try {
        const token = localStorage.getItem('token');
        const response = await fetch(`${API_URL}/api/declarations`, {
          headers: { 'Authorization': `Bearer ${token}` }
        });
        
        if (response.ok) {
          this.declarations = await response.json();
        }
      } catch (error) {
        console.error('Fetch error:', error);
      }
    },
    
    viewDeclaration(decl) {
      window.location.href = `/declaration/${decl.id}`;
    },
    
    formatDate(date) {
      return new Date(date).toLocaleDateString('fr-FR');
    }
  },
  
  mounted() {
    const token = localStorage.getItem('token');
    if (token) {
      this.isAuthenticated = true;
      this.fetchDeclarations();
    }
  }
};

if (typeof Vue !== 'undefined') {
  new Vue(app);
}