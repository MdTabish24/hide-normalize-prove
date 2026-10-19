"""Small statistics helpers with no scipy dependency (also used inside the slim image)."""
import math


def wilson(correct, n, z=1.959963984540054):
    """95% Wilson score interval for a proportion."""
    p, denominator = correct / n, 1 + z * z / n
    center = (p + z * z / (2 * n)) / denominator
    half = z * ((p * (1 - p) / n + z * z / (4 * n * n)) ** 0.5) / denominator
    return [center - half, center + half]


def ks_2samp(a, b):
    """Two-sample Kolmogorov-Smirnov statistic D and asymptotic two-sided p-value."""
    a, b = sorted(a), sorted(b)
    n, m, i, j, d = len(a), len(b), 0, 0, 0.0
    while i < n and j < m:
        value = min(a[i], b[j])
        while i < n and a[i] == value:
            i += 1
        while j < m and b[j] == value:
            j += 1
        d = max(d, abs(i / n - j / m))
    if d == 0:
        return 0.0, 1.0
    root = math.sqrt(n * m / (n + m))
    lam = (root + 0.12 + 0.11 / root) * d
    p = 2 * sum((-1) ** (k - 1) * math.exp(-2 * k * k * lam * lam) for k in range(1, 101))
    return d, min(1.0, max(0.0, p))


def percentile(values, q):
    """Linear-interpolation percentile, q in [0, 100]."""
    values = sorted(values)
    position = (len(values) - 1) * q / 100
    low, high = math.floor(position), math.ceil(position)
    return values[low] + (values[high] - values[low]) * (position - low)


def summary(values):
    return {"n": len(values), "median": percentile(values, 50), "p95": percentile(values, 95),
            "max": max(values), "min": min(values)}
