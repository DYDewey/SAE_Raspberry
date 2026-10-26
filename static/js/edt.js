// Emploi du temps : un clic sur un cours ouvre le panneau d'émargement à droite.
(function () {
    const panneau = new bootstrap.Offcanvas(document.getElementById('panneau'));
    const contenu = document.getElementById('panneau-contenu');

    let courant = null;      // cours affiché, pour recharger le panneau après une validation manuelle

    async function ouvrir(idSeance, avec, sansAttente) {
        courant = [idSeance, avec];
        if (!sansAttente) {
            contenu.innerHTML = '<div class="text-center py-5"><div class="spinner-border text-primary"></div></div>';
            panneau.show();
        }
        try {
            const reponse = await fetch(`/admin/seances/${idSeance}/panneau?avec=${avec || ''}`);
            if (reponse.redirected && reponse.url.includes('/login')) {
                window.location = reponse.url;          // session expirée
                return;
            }
            contenu.innerHTML = await reponse.text();
        } catch (e) {
            contenu.innerHTML = '<div class="alert alert-danger">Impossible de charger l\'émargement.</div>';
        }
    }

    window.rechargerPanneau = () => courant && ouvrir(courant[0], courant[1], true);

    document.querySelectorAll('.cours-carte').forEach(carte => {
        carte.addEventListener('click', () => ouvrir(carte.dataset.seance, carte.dataset.avec));
        carte.addEventListener('keydown', e => {
            if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); ouvrir(carte.dataset.seance, carte.dataset.avec); }
        });
    });
})();
