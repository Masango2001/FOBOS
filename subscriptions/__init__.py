"""Application Django FOBOS : abonnements SaaS.

Porte les plans, les offres 1/2/3 mois, l'essai de 3 jours et le contrôle
d'accès aux fonctionnalités. La confirmation d'un Payment purpose=subscription
déclenche l'activation de la Subscription (idempotente).
"""
