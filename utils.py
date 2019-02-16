import sys
import numpy as np
from scipy.stats import gamma, invgamma, wishart, norm, bernoulli
from scipy.stats import beta as beta_dist
from scipy.stats import multivariate_normal as mv_norm
from scipy import special
from ars import ARS
import mpmath
from numba import jit, njit, autojit, vectorize, guvectorize, float64, float32

# the maximum positive integer for use in setting the ARS seed
maxsize = sys.maxsize


# def draw_gamma_ras(a, theta, size=1):
#     """
#     returns Gamma distributed samples according to the Rasmussen (2000) definition
#     """
#     return gamma.rvs(0.5 * a, loc=0, scale=2.0 * theta / a, size=size)


def draw_gamma(a, theta, size=1):
    """
    returns Gamma distributed samples
    """
    return gamma.rvs(a, loc=0, scale=theta, size=size)


def draw_invgamma(a, theta, size=1):
    """
    returns inverse Gamma distributed samples
    """
    return invgamma.rvs(a, loc=0, scale=theta, size=size)


def draw_wishart(df, scale, size=1):
    """
    returns Wishart distributed samples
    """
    return wishart.rvs(df=df, scale=scale, size=size)


def draw_normal(loc=0, scale=1, size=1):
    '''
    returns Normal distributed samples
    '''
    return norm.rvs(loc=loc, scale=scale, size=size)


def draw_MVNormal(mean=0, cov=1, size=1):
    """
    returns multivariate normally distributed samples
    """
    return mv_norm.rvs(mean=mean, cov=cov, size=size)


def draw_Bernoulli(p):
    '''
    returns Bernoulli distributed samples
    '''
    return bernoulli.rvs(p)


def draw_Beta_dist(delta_a, delta_b):
    '''
    returns Bernoulli distributed samples
    '''
    return beta_dist.rvs(delta_a, delta_b)


@jit(nogil=True,)
def Asymmetric_Gassian_Distribution_pdf(x_k, mu_jk, s_ljk, s_rjk, mu_jk_irr, s_ljk_irr, s_rjk_irr, rho):
    '''
    Asymmetric Gassuian distribution pdf for all observations
    '''
    y_k = np.zeros(x_k.shape[0])
    for i, xik in enumerate(x_k):
        if xik < mu_jk:
            y_k[i] += rho * np.sqrt(2/np.pi)/(np.power(s_ljk, -0.5) + np.power(s_rjk, -0.5))\
                   * np.exp(- 0.5 * s_ljk * (xik- mu_jk)**2)
        else:
            y_k[i] += rho * np.sqrt(2/np.pi)/(np.power(s_ljk, -0.5) + np.power(s_rjk, -0.5))\
                   * np.exp(- 0.5 * s_rjk * (xik- mu_jk)**2)
        if xik < mu_jk_irr:
            y_k[i] += (1 - rho) * np.sqrt(2/np.pi)/(np.power(s_ljk_irr, -0.5) + np.power(s_rjk_irr, -0.5))\
                   * np.exp(- 0.5 * s_ljk_irr * (xik- mu_jk_irr)**2)
        else:
            y_k[i] += (1 - rho) * np.sqrt(2/np.pi)/(np.power(s_ljk_irr, -0.5) + np.power(s_rjk_irr, -0.5))\
                   * np.exp(- 0.5 * s_rjk_irr * (xik- mu_jk_irr)**2)
    return y_k


@jit(nogil=True,)
def AGD_pdf(x_k, mu, s_l, s_r):
    '''
    Asymmetric Gassuian distribution pdf for single observation
    '''
    if x_k < mu:
        return np.sqrt(2 / np.pi) / (np.power(s_l, -0.5) + np.power(s_r, -0.5)) \
               * np.exp(- 0.5 * s_l * (x_k - mu) ** 2)
    else:
        return np.sqrt(2 / np.pi) / (np.power(s_l, -0.5) + np.power(s_r, -0.5)) \
               * np.exp(- 0.5 * s_r * (x_k - mu) ** 2)


def AGD_pdf_feature_selction(x, j, D, rho, mu, s_l, s_r, mu_irr, s_l_irr, s_r_irr):
    '''
    Asymmetric Gassuian distribution pdf with feature selection
    '''
    y = mpmath.mpf(1.0)
    for k in range(D):
        y *= (rho[j, k] * AGD_pdf(x[k], mu[j, k], s_l[j, k], s_r[j, k]) + (1-rho[j, k])*
              AGD_pdf(x[k], mu_irr[j, k], s_l_irr[j, k], s_r_irr[j, k]))
    return y


def compare_mu_jk(mu_jk, previous_mu_jk, s_ljk, s_rjk, r, lam, z, j, k, X):
    '''
    compare candiate with previous parameter
    when sampling mu_jk, we use z[i,j,k] but (1 - z[i,j,k] for irrelevant feature.
    '''
    compared_log_likelihood = 0
    for i, x_i in enumerate(X):
        compared_log_likelihood += z[i, j, k] * (np.log(AGD_pdf(x_i[k], mu_jk, s_ljk, s_rjk))- \
                                                 np.log(AGD_pdf(x_i[k], previous_mu_jk, s_ljk, s_rjk)))
    likelihood_ratio = np.exp(compared_log_likelihood)
    prior = draw_normal(loc=lam[k], scale=1/r[k])[0] / draw_normal(loc=lam[k], scale=1/r[k])[0]
    return likelihood_ratio * prior


def MH_Sampling_posterior_mu_jk(mu_jk, s_ljk, s_rjk, r, lam, z, j, k, X):
    '''
    Metropolis Hastings sampling for the postiors of mu_jk parameter
    '''
    n = 750
    x = mu_jk
    vec = []
    vec.append(x)
    for i in range(n):
        candidate = norm.rvs(x, 0.75, 1)[0]
        # acceptance probability
        alpha = min([1., compare_mu_jk(candidate, x, s_ljk, s_rjk, r, lam, z, j, k, X)])
        u = np.random.uniform(0,1)
        if u < alpha:
            x = candidate
            vec.append(x)
    return vec[-1]


def compare_s_ljk(s_ljk, previous_s_ljk, mu_jk, s_rjk, beta, w, z, j, k, X):
    '''
    compare candiate with previous parameter
    when sampling s_ljk, we use z[i,j,k] but (1 - z[i,j,k] for irrelevant feature.
    '''
    compared_log_likelihood = 0.0
    for i, x_i in enumerate(X):
        compared_log_likelihood += z[i, j, k] * (np.log(AGD_pdf(x_i[k], mu_jk, s_ljk, s_rjk))- \
                                                 np.log(AGD_pdf(x_i[k], mu_jk, previous_s_ljk, s_rjk)))
    likelihood_ratio = np.exp(compared_log_likelihood)
    prior = draw_gamma(beta[k]/2, 2/(beta[k]*w[k]))[0] / draw_gamma(beta[k]/2, 2/(beta[k]*w[k]))[0]
    return likelihood_ratio * prior


def MH_Sampling_posterior_sljk(mu_jk, s_ljk, s_rjk, beta, w, z, j, k, X):
    '''
    Metropolis Hastings sampling for the postiors of s_ljk parameter
    '''
    n = 750
    x = s_ljk
    vec = []
    vec.append(x)
    for i in range(n):
        candidate = norm.rvs(x, 0.75, 1)[0]
        if candidate <= 0:
            candidate = np.abs(candidate)
        # acceptance probability
        alpha = min([1., compare_s_ljk(candidate, x, mu_jk, s_rjk, beta, w, z, j, k, X)])
        u = np.random.uniform(0,1)
        if u < alpha:
            x = candidate
            vec.append(x)
    return vec[-1]


def compare_s_rjk(s_rjk, previous_s_rjk, mu_jk, s_ljk, beta, w, z, j, k, X):
    '''
    compare candiate with previous parameter
    when sampling s_rjk, we use z[i,j,k] but (1 - z[i,j,k] for irrelevant feature.
    '''
    compared_log_likelihood = 0.0
    for i, x_i in enumerate(X):
        compared_log_likelihood += z[i, j, k] * (np.log(AGD_pdf(x_i[k], mu_jk, s_ljk, s_rjk))- \
                                                 np.log(AGD_pdf(x_i[k], mu_jk, s_ljk, previous_s_rjk)))
    likelihood_ratio = np.exp(compared_log_likelihood)
    prior = draw_gamma(beta[k]/2, 2/(beta[k]*w[k]))[0] / draw_gamma(beta[k]/2, 2/(beta[k]*w[k]))[0]
    return likelihood_ratio * prior


def MH_Sampling_posterior_srjk(mu_jk, s_ljk, s_rjk, beta, w, z, j, k, X):
    '''
    Metropolis Hastings sampling for the postiors of s_rjk parameter
    '''
    n = 750
    x = s_rjk
    vec = []
    vec.append(x)
    for i in range(n):
        candidate = norm.rvs(x, 0.75, 1)[0]
        if candidate <= 0:
            continue
        # acceptance probability
        alpha = min([1., compare_s_rjk(candidate, x, mu_jk, s_ljk, beta, w, z, j, k, X)])
        u = np.random.uniform(0,1)
        if u < alpha:
            x = candidate
            vec.append(x)
    return vec[-1]


def compare_delta_a(delta_a, previous_delta_a, delta_b, rho, k, M):
    '''
    compare candiate with previous parameter
    when sampling s_rjk, we use z[i,j,k] but (1 - z[i,j,k] for irrelevant feature.
    '''
    compared_log_likelihood = M * (special.gammaln(delta_a + delta_b) - special.gammaln(delta_a) -
                        special.gammaln(previous_delta_a + delta_b) + special.gammaln(previous_delta_a))
    for j in range(M):
        compared_log_likelihood += (delta_a - previous_delta_a) * np.log(rho[j, k])
    likelihood_ratio = np.exp(compared_log_likelihood)
    prior = draw_gamma(2, 0.5)[0] / draw_gamma(2, 0.5)[0]
    return likelihood_ratio * prior


def MH_Sampling_posterior_delta_a(delta_a, delta_b, rho, k, M):
    '''
    Metropolis Hastings sampling for the postiors of delta_a parameter
    '''
    n = 750
    x = delta_a
    vec = []
    vec.append(x)
    for i in range(n):
        candidate = norm.rvs(x, 0.75, 1)[0]
        if candidate <= 0:
            continue
        # acceptance probability
        alpha = min([1., compare_delta_a(candidate, x, delta_b, rho, k, M)])
        u = np.random.uniform(0,1)
        if u < alpha:
            x = candidate
            vec.append(x)
    return vec[-1]


def compare_delta_b(delta_b, previous_delta_b, delta_a, rho, k, M):
    '''
    compare candiate with previous parameter
    when sampling s_rjk, we use z[i,j,k] but (1 - z[i,j,k] for irrelevant feature.
    '''
    compared_log_likelihood = M * (special.gammaln(delta_a + delta_b) - special.gammaln(delta_b) -
                        special.gammaln(delta_a + previous_delta_b) + special.gammaln(previous_delta_b))
    for j in range(M):
        compared_log_likelihood += (delta_b - previous_delta_b) * np.log(1-rho[j, k])
    likelihood_ratio = np.exp(compared_log_likelihood)
    prior = draw_gamma(2, 0.5)[0] / draw_gamma(2, 0.5)[0]
    return likelihood_ratio * prior


def MH_Sampling_posterior_delta_b(delta_a, delta_b, rho, k, M):
    '''
    Metropolis Hastings sampling for the postiors of delta_a parameter
    '''
    n = 750
    x = delta_b
    vec = []
    vec.append(x)
    for i in range(n):
        candidate = norm.rvs(x, 0.75, 1)[0]
        if candidate <= 0:
            continue
        # acceptance probability
        alpha = min([1., compare_delta_b(candidate, x, delta_a, rho, k, M)])
        u = np.random.uniform(0,1)
        if u < alpha:
            x = candidate
            vec.append(x)
    return vec[-1]


def integral_approx(X, lam, r, beta_l, beta_r, w_l, w_r, delta_a, delta_b, size=20):
    """
    estimates the integral
    """
    N, D = X.shape
    temp = np.zeros(len(X))
    i = 0
    while i < size:
        # mu = np.array([np.squeeze(norm.rvs(loc=lam[k], scale=1/r[k], size=1)) for k in range(D)])
        mu = draw_MVNormal(mean=lam, cov=1/r)
        s_l = np.array([np.squeeze(draw_gamma(beta_l[k] / 2, 2 / (beta_l[k] * w_l[k]))) for k in range(D)])
        s_r = np.array([np.squeeze(draw_gamma(beta_r[k] / 2, 2 / (beta_r[k] * w_r[k]))) for k in range(D)])
        mu_irr = draw_MVNormal(mean=lam, cov=1/r)
        s_l_irr = np.array([np.squeeze(draw_gamma(beta_l[k] / 2, 2 / (beta_l[k] * w_l[k]))) for k in range(D)])
        s_r_irr = np.array([np.squeeze(draw_gamma(beta_r[k] / 2, 2 / (beta_r[k] * w_r[k]))) for k in range(D)])
        rho = draw_Beta_dist(delta_a, delta_b)
        ini = np.ones(len(X))
        for k in range(D):
            # use metropolis-hastings algorithm to draw sampling from AGD
            # the size parameter is the required sampling number which is equal to the dataset's number
            # the n parameter is MH algorithm itering times,because the acceptance rate should be 25%-40%
            temp_para = Asymmetric_Gassian_Distribution_pdf(X[:, k], mu[k], s_l[k], s_r[k], mu_irr[k],
                                                            s_l_irr[k], s_r_irr[k], rho[k])
            ini *= temp_para
        temp += ini
        i += 1
    return temp/float(size)


def log_p_alpha(alpha, k, N):
    """
    the log of eq15 (Rasmussen 2000)
    """
    return (k - 1.5)*np.log(alpha) - 0.5/alpha + special.gammaln(alpha) - special.gammaln(N + alpha)


def log_p_alpha_prime(alpha, k, N):
    """
    the derivative (wrt alpha) of the log of eq 15 (Rasmussen 2000)
    """
    return (k - 1.5)/alpha + 0.5/(alpha*alpha) + special.psi(alpha) - special.psi(alpha + N)


def log_p_beta(beta, M, cumculative_sum_equation=1):
    return -2*M*special.gammaln(beta/2) \
        - 0.5/beta \
        + (beta*M-1.5)*np.log(beta/2) \
        + 0.5*beta*cumculative_sum_equation


def log_p_beta_prime(beta, M, cumculative_sum_equation=1):
    return -2*M*special.psi(0.5*beta) \
        + 0.5/beta**2 \
        + M*np.log(0.5*beta) \
        + (2*M*beta -3)/beta \
        + 0.5*cumculative_sum_equation


def draw_alpha(k, N, size=1):
    """
    draw alpha from posterior (depends on k, N), eq 15 (Rasmussen 2000), using ARS
    Make it robust with an expanding range in case of failure
    """
    ars = ARS(log_p_alpha, log_p_alpha_prime, xi=[0.1, 5], lb=0, ub=np.inf, k=k, N=N)
    return ars.draw(size)


def draw_beta_ars(w, s, s_irr, M, k, size=1):
    D = 2
    cumculative_sum_equation = 0
    for sj in s:
        cumculative_sum_equation += np.log(sj[k])
        cumculative_sum_equation += np.log(w[k])
        cumculative_sum_equation -= w[k]*sj[k]
    for sj_irr in s_irr:
        cumculative_sum_equation += np.log(sj_irr[k])
        cumculative_sum_equation -= w[k]*sj_irr[k]
    lb = D
    ars = ARS(log_p_beta, log_p_beta_prime, xi=[lb + 15], lb=lb, ub=float("inf"), \
             M=M, cumculative_sum_equation=cumculative_sum_equation)
    return ars.draw(size)



def draw_indicator(pvec):
    """
    draw stochastic indicator values from multinominal distributions, check wiki
    """
    res = np.zeros(pvec.shape[1])
    # loop over each data point
    for j in range(pvec.shape[1]):
        c = np.cumsum(pvec[ : ,j])        # the cumulative un-scaled probabilities
        R = np.random.uniform(0, c[-1], 1)        # a random number
        r = (c - R)>0                     # truth table (less or greater than R)
        y = (i for i, v in enumerate(r) if v)    # find first instant of truth
        try:
            res[j] = y.__next__()           # record component index
        except:                 # if no solution (must have been all zeros)
            res[j] = np.random.randint(0, pvec.shape[0]) # pick uniformly
    return res


def draw_posterior_z(X, pi, rho, mu, s_l, s_r, mu_irr, s_l_irr, s_r_irr, N, M, D):
    Z_ij = np.zeros((N, M), dtype=mpmath.mpf)
    Z_i = np.zeros(N, dtype=mpmath.mpf)
    Z_ij_posteriors = np.zeros((N, M), dtype=mpmath.mpf)
    posterior_z = np.zeros((N, M, D))
    for i in range(N):
        for j in range(M):
            Z_ij_posteriors[i] = pi[j] * AGD_pdf_feature_selction(X[i], j, D, rho, mu, s_l, s_r, mu_irr, s_l_irr, s_r_irr)
            # Z_ij[i, j] = pi[j] * AGD_pdf_feature_selction(X[i], j, D, rho, mu, s_l, s_r, mu_irr, s_l_irr, s_r_irr)
        # Z_i[i] = np.sum(Z_ij[i])
        # Z_ij_posteriors[i] = Z_ij[i] / Z_i[i]
    for i in range(N):
        for j in range(M):
            for k in range(D):
                # rele_result = rho[j, k] * AGD_pdf(X[i, k], mu[j, k], s_l[j, k], s_r[j, k])
                # irr_result = (1 - rho[j, k]) * AGD_pdf(X[i, k], mu_irr[j, k], s_l_irr[j, k], s_r_irr[j, k])
                posterior_z[i, j, k] = rho[j, k] * AGD_pdf(X[i, k], mu[j, k], s_l[j, k], s_r[j, k]) * Z_ij_posteriors[i, j]
    return posterior_z