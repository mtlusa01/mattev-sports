// ============================================
// FIREBASE AUTH MODULE
// ============================================

const firebaseConfig = {
    apiKey: "AIzaSyBZtHCHKutZzbQXgwUPfOfJvCtbQh3e-r4",
    authDomain: "edge-factor-elite.firebaseapp.com",
    projectId: "edge-factor-elite",
    storageBucket: "edge-factor-elite.firebasestorage.app",
    messagingSenderId: "469124201044",
    appId: "1:469124201044:web:d1466e2b198db6d7df4bc1",
    measurementId: "G-Z3MJD626QS"
};

firebase.initializeApp(firebaseConfig);
const auth = firebase.auth();
const db = firebase.firestore();

// ============================================
// AUTH STATE MANAGEMENT
// ============================================
let currentUser = null;
let userProfile = null;

const DEFAULT_SETTINGS = {
    defaultSport: 'nba',
    defaultView: 'games',
    oddsFormat: 'american',
    darkMode: true,
    notifications: false,
    betSize: 10,
    unitSize: 10,
    showEV: true,
    showHitRate: true,
    minConfidence: 55,
    minEV: 3,
    bankroll: null
};

function initAuth() {
    auth.onAuthStateChanged(async (user) => {
        currentUser = user;

        if (user) {
            userProfile = await getUserProfile(user.uid);
            db.collection('users').doc(user.uid).update({
                lastLogin: firebase.firestore.FieldValue.serverTimestamp()
            }).catch(() => {});
            updateNavForLoggedIn(user, userProfile);
        } else {
            userProfile = null;
            updateNavForLoggedOut();
        }
    });
}

// ============================================
// SIGN UP
// ============================================
async function signUp(email, password, displayName) {
    try {
        const credential = await auth.createUserWithEmailAndPassword(email, password);
        const user = credential.user;
        await user.updateProfile({ displayName: displayName });
        await db.collection('users').doc(user.uid).set({
            displayName: displayName,
            email: email,
            createdAt: firebase.firestore.FieldValue.serverTimestamp(),
            role: 'free',
            lastLogin: firebase.firestore.FieldValue.serverTimestamp(),
            settings: { ...DEFAULT_SETTINGS }
        });
        return { success: true, user: user };
    } catch (error) {
        return { success: false, error: getErrorMessage(error.code) };
    }
}

// ============================================
// SIGN IN
// ============================================
async function signIn(email, password) {
    try {
        const credential = await auth.signInWithEmailAndPassword(email, password);
        return { success: true, user: credential.user };
    } catch (error) {
        return { success: false, error: getErrorMessage(error.code) };
    }
}

// ============================================
// GOOGLE SIGN IN
// ============================================
async function signInWithGoogle() {
    try {
        const provider = new firebase.auth.GoogleAuthProvider();
        const credential = await auth.signInWithPopup(provider);
        const user = credential.user;
        const doc = await db.collection('users').doc(user.uid).get();
        if (!doc.exists) {
            await db.collection('users').doc(user.uid).set({
                displayName: user.displayName || user.email.split('@')[0],
                email: user.email,
                createdAt: firebase.firestore.FieldValue.serverTimestamp(),
                role: 'free',
                lastLogin: firebase.firestore.FieldValue.serverTimestamp(),
                settings: { ...DEFAULT_SETTINGS }
            });
        }
        return { success: true, user: user };
    } catch (error) {
        return { success: false, error: getErrorMessage(error.code) };
    }
}

// ============================================
// SIGN OUT
// ============================================
async function handleSignOut() {
    try {
        await auth.signOut();
        window.location.href = 'index.html';
    } catch (error) {
        console.error('Sign out error:', error);
    }
}

// ============================================
// PASSWORD RESET
// ============================================
async function resetPassword(email) {
    try {
        await auth.sendPasswordResetEmail(email);
        return { success: true };
    } catch (error) {
        return { success: false, error: getErrorMessage(error.code) };
    }
}

// ============================================
// USER PROFILE
// ============================================
async function getUserProfile(uid) {
    try {
        const doc = await db.collection('users').doc(uid).get();
        return doc.exists ? doc.data() : null;
    } catch (error) {
        return null;
    }
}

async function updateUserProfile(data) {
    if (!currentUser) return { success: false, error: 'Not logged in' };
    try {
        await db.collection('users').doc(currentUser.uid).update(data);
        if (data.displayName) {
            await currentUser.updateProfile({ displayName: data.displayName });
        }
        return { success: true };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

async function saveUserSettings(settings) {
    if (!currentUser) return { success: false, error: 'Not logged in' };
    try {
        await db.collection('users').doc(currentUser.uid).update({ settings: settings });
        return { success: true };
    } catch (error) {
        return { success: false, error: error.message };
    }
}

async function getUserSettings() {
    if (!currentUser) return null;
    const profile = await getUserProfile(currentUser.uid);
    return profile?.settings || null;
}

// ============================================
// NAV UI UPDATES
// ============================================
function updateNavForLoggedIn(user, profile) {
    const navRight = document.querySelector('.nav-right');
    if (!navRight) return;

    const displayName = user.displayName || user.email.split('@')[0];
    const initial = displayName.charAt(0).toUpperCase();
    const role = profile?.role || 'free';
    const roleBadge = role === 'admin' ? 'Admin' : 'Free';

    let authSection = document.getElementById('auth-section');
    if (authSection) authSection.remove();

    authSection = document.createElement('div');
    authSection.id = 'auth-section';
    authSection.className = 'user-menu';
    authSection.innerHTML = `
        <button class="user-avatar" onclick="toggleUserMenu()">${initial}</button>
        <div class="user-dropdown" id="user-dropdown">
            <div class="dropdown-header">
                <span class="user-name">${displayName}</span>
                <span class="user-email">${user.email}</span>
                <span class="user-role">${roleBadge}</span>
            </div>
            <div class="dropdown-divider"></div>
            <a href="profile.html" class="dropdown-item">Settings</a>
            <a href="#" class="dropdown-item" onclick="handleSignOut(); return false;">Sign Out</a>
        </div>
    `;
    navRight.appendChild(authSection);

    const loginBtn = navRight.querySelector('.auth-link');
    if (loginBtn) loginBtn.remove();

    // Update mobile drawer auth
    const mobileAuth = document.getElementById('mobile-drawer-auth');
    if (mobileAuth) {
        mobileAuth.innerHTML = `
            <div class="mobile-drawer-profile">
                <div class="mobile-drawer-avatar">${initial}</div>
                <div class="mobile-drawer-user-info">
                    <span class="mobile-drawer-name">${displayName}</span>
                    <span class="mobile-drawer-email">${user.email}</span>
                </div>
            </div>
            <div class="mobile-drawer-links">
                <a href="profile.html">
                    <span class="menu-icon">&#9881;&#65039;</span> Settings
                </a>
                <a href="#" onclick="handleSignOut(); return false;" style="color:#ef4444;">
                    <span class="menu-icon">&#128682;</span> Sign Out
                </a>
            </div>
        `;
    }
}

function updateNavForLoggedOut() {
    const navRight = document.querySelector('.nav-right');
    if (!navRight) return;

    const authSection = document.getElementById('auth-section');
    if (authSection) authSection.remove();

    if (!navRight.querySelector('.auth-link')) {
        const loginLink = document.createElement('a');
        loginLink.href = 'login.html';
        loginLink.className = 'nav-link auth-link';
        loginLink.innerHTML = '<span class="login-btn-pill">Log In</span>';
        navRight.appendChild(loginLink);
    }

    // Update mobile drawer auth
    const mobileAuth = document.getElementById('mobile-drawer-auth');
    if (mobileAuth) {
        mobileAuth.innerHTML = '<a href="login.html" class="mobile-drawer-login-btn">&#128100; Log In / Sign Up</a>';
    }
}

function toggleUserMenu() {
    const dropdown = document.getElementById('user-dropdown');
    if (dropdown) dropdown.classList.toggle('active');
}

document.addEventListener('click', (e) => {
    const dropdown = document.getElementById('user-dropdown');
    const avatar = document.querySelector('.user-avatar');
    if (dropdown && !dropdown.contains(e.target) && e.target !== avatar) {
        dropdown.classList.remove('active');
    }
});

// ============================================
// ERROR MESSAGES
// ============================================
function getErrorMessage(code) {
    const messages = {
        'auth/email-already-in-use': 'An account with this email already exists.',
        'auth/invalid-email': 'Please enter a valid email address.',
        'auth/operation-not-allowed': 'This sign-in method is not enabled.',
        'auth/weak-password': 'Password must be at least 6 characters.',
        'auth/user-disabled': 'This account has been disabled.',
        'auth/user-not-found': 'No account found with this email.',
        'auth/wrong-password': 'Incorrect password.',
        'auth/too-many-requests': 'Too many attempts. Please try again later.',
        'auth/popup-closed-by-user': 'Sign-in popup was closed.',
        'auth/network-request-failed': 'Network error. Check your connection.',
        'auth/invalid-credential': 'Invalid email or password.',
    };
    return messages[code] || 'An error occurred. Please try again.';
}

// ============================================
// INITIALIZE
// ============================================
document.addEventListener('DOMContentLoaded', () => {
    initAuth();
});
