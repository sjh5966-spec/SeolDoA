# Execution proxy methodology

Status: methodological documentation for the frozen paper-trading execution model. This file does not change the research signal.

## Corwin-Schultz-style OHLC spread proxy

The implementation uses the Corwin-Schultz two-day high-low closed form:

- beta = log(H_t/L_t)^2 + log(H_{t-1}/L_{t-1})^2
- gamma = log(max(H_t,H_{t-1}) / min(L_t,L_{t-1}))^2
- alpha = (sqrt(2*beta)-sqrt(beta))/(3-2*sqrt(2)) - sqrt(gamma/(3-2*sqrt(2)))
- negative alpha is clipped to zero
- S = 2*(exp(alpha)-1)/(1+exp(alpha))

This is consistent with Corwin and Schultz (Journal of Finance, 2012, DOI 10.1111/j.1540-6261.2012.01729.x) and common implementations that clip negative alpha estimates to zero.

Important limitation: the research implementation does NOT apply the paper's overnight-return adjustment. Therefore the field is deliberately named and interpreted as a `Corwin-Schultz-style OHLC spread proxy`, not as a measured quoted spread and not as a claim of exact canonical CS implementation.

## Round-trip cost convention

The CS output is a proportional effective bid-ask spread proxy. For paper execution stress:

- 1.0x CS proxy is the primary full-spread round-trip reference component.
- 2.0x CS proxy is a conservative sensitivity, not a second estimate of the same measured spread.
- impact is added separately as k * sqrt(position_notional / ADV20).
- k=0.01 is the paper reference scenario; k=0.005, 0.02 and 0.05 remain mandatory sensitivities.

The cost model is not calibrated to realized microcap executions. Expected proxy cost and observed execution/slippage must remain separate.

## Change-control rule

Do not add overnight adjustment, replace the spread proxy, or recalibrate k based on paper returns without a dated preregistration and recomputation of all dependent execution results.
