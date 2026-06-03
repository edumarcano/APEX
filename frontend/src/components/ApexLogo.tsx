import { useEffect, useState, type ReactElement } from 'react'
import type { SystemState } from '../types/telemetry'

export interface ApexLogoProps {
  step: number | null
  status: SystemState
  isSpeaking?: boolean
  reminderPulseCount?: number
  className?: string
}

export function ApexLogo({
  step,
  status,
  isSpeaking = false,
  reminderPulseCount = 0,
  className = '',
}: ApexLogoProps): ReactElement {
  const [pulseActive, setPulseActive] = useState(false)

  // Listen to reminder submission events to trigger an 800ms system-wide flash
  useEffect(() => {
    if (reminderPulseCount > 0) {
      setPulseActive(true)
      const timer = window.setTimeout(() => setPulseActive(false), 800)
      return () => window.clearTimeout(timer)
    }
  }, [reminderPulseCount])

  const isError = status === 'error'
  const activeStep = step ?? 0
  const hasDelivered = status === 'success' || activeStep >= 4

  // =========================================================
  // DYNAMIC STATE STYLING MATRICES
  // =========================================================

  const baseBlue = 'apex-blue-metal apex-blue-metal--base'
  const activeBlue = 'apex-blue-metal apex-blue-metal--active'
  const surgeBlue = 'apex-blue-metal apex-blue-metal--surge'

  const getBlueSegmentClass = (segmentStep: number): string => {
    if (pulseActive) {
      return `transition-all duration-300 ease-out ${surgeBlue}`
    }

    const blueMetal =
      activeStep >= segmentStep || hasDelivered ? activeBlue : baseBlue

    return `transition-all duration-700 ease-in-out ${blueMetal}`
  }

  const surgeGold = 'apex-core-metal apex-core-metal--gold-surge'
  const dormantCore = 'apex-core-metal apex-core-metal--dormant'
  const greenCore = 'apex-core-metal apex-core-metal--green'
  const redCore = 'apex-core-metal apex-core-metal--red'
  const goldActiveCore = 'apex-core-metal apex-core-metal--gold-active'
  const goldActiveBreathing = `${goldActiveCore} animate-[pulse_3s_ease-in-out_infinite]`

  const getGoldSegmentClass = (segmentStep: number): string => {
    if (pulseActive) {
      return `transition-all duration-300 ease-out ${surgeGold}`
    }

    let fillClass = dormantCore

    if (isError) {
      fillClass = redCore
    } else if (hasDelivered) {
      fillClass = isSpeaking ? goldActiveBreathing : goldActiveCore
    } else if (activeStep >= segmentStep) {
      fillClass = greenCore
    }

    return `transition-all duration-700 ease-in-out ${fillClass}`
  }

  return (
    <div className={`relative flex items-center justify-center ${className}`} aria-hidden="true">
      <svg 
        viewBox="0 0 5208 5420" 
        className="h-full w-full overflow-visible select-none"
        xmlns="http://www.w3.org/2000/svg"
      >
        <defs>
          <linearGradient
            id="apexBlueMetal"
            x1="620"
            y1="560"
            x2="4520"
            y2="4920"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#6EA8FF" />
            <stop offset="12%" stopColor="#1F6FE5" />
            <stop offset="30%" stopColor="#0F4DB8" />
            <stop offset="55%" stopColor="#082F7A" />
            <stop offset="78%" stopColor="#041C51" />
            <stop offset="100%" stopColor="#164FC2" />
          </linearGradient>

          <linearGradient
            id="apexGoldMetal"
            x1="2110"
            y1="520"
            x2="3090"
            y2="5410"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#FFF3B0" />
            <stop offset="16%" stopColor="#FFD166" />
            <stop offset="34%" stopColor="#FBBF24" />
            <stop offset="56%" stopColor="#D97706" />
            <stop offset="74%" stopColor="#92400E" />
            <stop offset="100%" stopColor="#F59E0B" />
          </linearGradient>

          <linearGradient
            id="apexGreenMetal"
            x1="2110"
            y1="520"
            x2="3090"
            y2="5410"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#D1FAE5" />
            <stop offset="18%" stopColor="#6EE7B7" />
            <stop offset="38%" stopColor="#39FF88" />
            <stop offset="60%" stopColor="#10B981" />
            <stop offset="80%" stopColor="#047857" />
            <stop offset="100%" stopColor="#A7F3D0" />
          </linearGradient>

          <linearGradient
            id="apexRedMetal"
            x1="2110"
            y1="520"
            x2="3090"
            y2="5410"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#FECACA" />
            <stop offset="18%" stopColor="#F87171" />
            <stop offset="40%" stopColor="#DC2626" />
            <stop offset="62%" stopColor="#991B1B" />
            <stop offset="82%" stopColor="#450A0A" />
            <stop offset="100%" stopColor="#EF4444" />
          </linearGradient>

          <linearGradient
            id="apexDormantMetal"
            x1="2110"
            y1="520"
            x2="3090"
            y2="5410"
            gradientUnits="userSpaceOnUse"
          >
            <stop offset="0%" stopColor="#92400E" />
            <stop offset="35%" stopColor="#78350F" />
            <stop offset="68%" stopColor="#451A03" />
            <stop offset="100%" stopColor="#B45309" />
          </linearGradient>
        </defs>

        <style>
          {`
            .apex-blue-metal {
              fill: url(#apexBlueMetal);
            }

            .apex-blue-metal--base {
              opacity: 0.3;
            }

            .apex-blue-metal--active {
              filter: drop-shadow(0 0 12px rgba(79, 143, 255, 0.75));
            }

            .apex-blue-metal--surge {
              filter: drop-shadow(0 0 24px rgba(79, 143, 255, 1));
            }

            .apex-core-metal {
              fill: url(#apexGoldMetal);
            }

            .apex-core-metal--dormant {
              fill: url(#apexDormantMetal);
              opacity: 0.2;
            }

            .apex-core-metal--green {
              fill: url(#apexGreenMetal);
              filter: drop-shadow(0 0 12px rgba(57, 255, 136, 0.8));
            }

            .apex-core-metal--red {
              fill: url(#apexRedMetal);
              filter: drop-shadow(0 0 14px rgba(220, 38, 38, 0.8));
            }

            .apex-core-metal--gold-active {
              fill: url(#apexGoldMetal);
              filter: drop-shadow(0 0 14px rgba(251, 191, 36, 0.85));
            }

            .apex-core-metal--gold-surge {
              fill: url(#apexGoldMetal);
              filter: drop-shadow(0 0 24px rgba(251, 191, 36, 1));
            }
          `}
        </style>

        {/* =========================================================
            OUTER BLUE SHELL LAYER
           ========================================================= */}
        
        {/* Stage 4: Crown */}
        <path 
          id="blue-crown-top"
          className={getBlueSegmentClass(4)}
          d="M2336.38 954.065L2463.38 757.565C2492.21 711.398 2556.68 607.664 2583.88 562.064C2611.08 516.464 2626.88 527.564 2644.88 553.064L2765.38 754.065L2889.88 954.065C2896.88 982.565 2890.14 1014.8 2847.38 1008.07C2793.38 999.565 2762.88 960.066 2730.38 1036.07L2725.38 1070.57L2719.88 1210.07C2730.38 1229.07 2739.38 1241.92 2805.88 1210.07C2881.88 1173.67 3054.88 1110.23 3136.88 1083.07C3152.38 1077.93 3194.38 1062.57 3173.38 1014.07C3145.54 949.776 2842.74 337.35 2680.77 37.0637C2648.38 -12.4355 2613.38 -10.9349 2575.88 37.0651C2414.38 336.065 2083.08 949.565 2049.88 1011.57C2016.68 1073.57 2061.38 1090.93 2076.88 1096.07C2158.88 1123.23 2341.88 1186.67 2417.88 1223.07C2493.88 1259.47 2489.88 1244.57 2506.38 1210.07V1070.07L2495.88 1036.07C2463.38 960.066 2430.38 1005.49 2377.88 1021.07C2336.38 1033.38 2329.38 982.565 2336.38 954.065Z"
        />

        {/* Stage 3: Upper Roots */}
        <g id="blue-upper-roots">
          <path 
            id="blue-upper-left"
            className={getBlueSegmentClass(3)}
            d="M1670.88 1812.56L1822.38 1519.56L1972.38 1237.06C2025.38 1144.56 2071.88 1168.06 2130.38 1189.56C2195.51 1213.5 2361.88 1321.06 2415.38 1419.56C2472.88 1551.06 2506.88 1780.06 2439.88 1969.06C2397.43 2088.81 2359.88 2116.06 2276.38 2103.06C2121.38 2046.73 1834.38 1935.56 1720.88 1903.06C1647.31 1882 1657.38 1832.4 1670.88 1812.56Z"
          />
          <path 
            id="blue-upper-right"
            className={getBlueSegmentClass(3)}
            d="M3543.38 1814.06L3396.88 1523.06L3245.78 1237.06C3192.78 1144.56 3143.88 1161.06 3085.38 1182.56C3020.24 1206.5 2843.88 1309.56 2802.78 1419.56C2738.88 1521.06 2711.88 1808.56 2766.38 1971.56C2806.67 2092.06 2835.98 2117.06 2936.88 2097.56C3085.88 2025.56 3319.38 1935.89 3489.88 1887.06C3554.48 1868.57 3551.38 1839.06 3543.38 1814.06Z"
          />
        </g>

        {/* Stage 2: Lower Roots */}
        <g id="blue-lower-roots">
          <path 
            id="blue-lower-left"
            className={getBlueSegmentClass(2)}
            d="M1193.88 2741.56L1389.88 2348.06C1421.21 2286.06 1495.88 2139.16 1543.88 2047.56C1591.88 1955.96 1678.55 1960.06 1715.88 1973.56C1733.55 1981.4 1809.88 2018.66 1973.88 2105.06C2137.88 2191.46 2264.55 2316.73 2307.38 2368.56C2442.38 2517.06 2456.88 2895.06 2389.88 3016.56C2326.17 3132.1 2323.38 3129.56 2191.38 3123.56C1948.38 3030.06 1471.88 2881.06 1295.88 2857.06C1172.41 2840.23 1183.68 2788.43 1193.63 2742.71L1193.88 2741.56Z"
          />
          <path 
            id="blue-lower-right"
            className={getBlueSegmentClass(2)}
            d="M4020.32 2741.56L3824.32 2348.06C3792.98 2286.06 3718.32 2139.16 3670.32 2047.56C3618.44 1948.56 3559.38 1946.49 3498.31 1973.56C3480.65 1981.4 3398.38 2011.66 3234.38 2098.06C3070.38 2184.46 2933.21 2319.73 2890.38 2371.56C2755.38 2520.06 2764.32 2892.96 2811.38 3022.56C2841.88 3106.56 2890.81 3129.56 3022.81 3123.56C3265.81 3030.06 3731.88 2859.56 3899.38 2827.56C3993.8 2809.53 4020.31 2797.06 4020.32 2741.56Z"
          />
        </g>

        {/* Stage 1: Trunk Base Legs */}
        <g id="blue-trunk-shell">
          <path 
            id="blue-base-left"
            className={getBlueSegmentClass(1)}
            d="M1855.38 3842.56L2237.38 3837.06C2403.38 3837.06 2346.88 3842.06 2280.38 3636.06L2222.88 3535.06L2146.38 3440.56C2021.38 3288.56 1776.52 3147.64 1482.88 3014.56C1178.38 2876.56 1148.38 2877.56 1082.38 2984.06L12.3775 5246.56C-19.6218 5304.06 12.3776 5375.56 116.378 5410.56C219.878 5422.06 387.713 5417.06 674.378 5417.06C965.378 5417.06 1009.38 5446.06 1101.88 5300.56C1266.21 4923.9 1612.28 4135.36 1671.88 3996.56C1731.48 3857.76 1804.38 3855.06 1855.38 3842.56Z"
          />
          <path 
            id="blue-base-right"
            className={getBlueSegmentClass(1)}
            d="M3357.14 3842.56H3004.38C2838.38 3842.56 2865.64 3842.06 2932.14 3636.06L2989.64 3535.06L3066.14 3440.56C3191.14 3288.56 3436 3147.64 3729.64 3014.56C4034.14 2876.56 4070.38 2879.06 4136.38 2985.56L5193.88 5244.56C5225.88 5302.06 5200.14 5375.56 5096.14 5410.56C4992.64 5422.06 4824.8 5417.06 4538.14 5417.06C4247.14 5417.06 4203.14 5446.06 4110.64 5300.56C3946.31 4923.9 3600.24 4135.36 3540.64 3996.56C3481.04 3857.76 3408.14 3855.06 3357.14 3842.56Z"
          />
        </g>

        {/* =========================================================
            INTERNAL CORE (4 BRANCH SECTIONS)
           ========================================================= */}
        
        {/* Gold Stage 1: Trunk Base */}
        <path 
          id="gold-stage-1"
          className={getGoldSegmentClass(1)}
          d="M2256.38 4639.56C2365.38 4389.56 2404.88 4050.06 2365.38 3843.56H2677.38H2856.88C2841.88 4054.06 2856.88 4389.56 2965.88 4639.56C3091.66 4928.06 3357.88 5174.56 3553.88 5310.06C3567.38 5338.4 3599.88 5397.22 3460.88 5405.06C3325.54 5412.7 2944.19 5411 2751.12 5410.13L2735.88 5410.06C2548.38 5410.9 1892.18 5412.06 1765.38 5410.06C1638.58 5410.06 1633.88 5350.9 1647.38 5322.56C1841.88 5200.56 2137.7 4911.76 2256.38 4639.56Z"
        />

        {/* Gold Stage 2: Lower Branches */}
        <path 
          id="gold-stage-2"
          className={getGoldSegmentClass(2)}
          d="M2200.38 3157.06H2298.38H2904.88H3002.88C3394.88 3006.56 3948.38 2805.06 3948.38 2843.56C3948.38 2912.69 3836.88 2921.06 3691.38 3006.56C3565.55 3056.9 3313.07 3190.85 3207.88 3273.56C3090.88 3365.56 2871.88 3617.56 2859.88 3843.06H2364.88C2352.88 3617.56 2127.38 3365.06 2010.38 3273.06C1905.18 3190.35 1637.71 3056.9 1511.88 3006.56C1366.38 2921.06 1261.27 2940.06 1265.37 2871.06C1266.24 2856.56 1819.88 3006.56 2200.38 3157.06Z"
        />

        {/* Gold Stage 3: Upper Branches */}
        <path 
          id="gold-stage-3"
          className={getGoldSegmentClass(3)}
          d="M1806.38 1998.56C1714.46 1959.84 1729.88 1951.06 1729.88 1925.06L2049.38 2037.56L2278.88 2130.06H2601.88H2904.88L2978.38 2105.56L3172.38 2020.06L3318.38 1963.06L3489.88 1904.06H3496.38C3496.38 1938.56 3487.3 1959.84 3395.38 1998.56C3001.38 2164.56 2828.3 2341.42 2774.88 2558.56C2712.88 2810.56 2773.88 3093.56 2902.38 3156.56H2571.88H2298.38C2426.88 3089.56 2496.82 2803.06 2426.88 2558.56C2365.38 2343.56 2200.38 2164.56 1806.38 1998.56Z"
        />

        {/* Gold Stage 4: Arrow Peak */}
        <path 
          id="gold-stage-4"
          className={getGoldSegmentClass(4)}
          d="M2371.88 1003.56C2351.88 1014.36 2346.88 982.064 2346.88 964.564L2608.88 555.064L2618.38 550.564L2627.38 555.064L2880.38 964.564C2882.38 982.064 2878.18 1012.76 2845.38 995.564C2812.58 978.364 2776.88 964.564 2776.88 964.564C2735.88 977.064 2714.38 1018.06 2703.88 1039.56V1223.06C2705.38 1239.4 2737.9 1259.56 2776.88 1243.06C2815.85 1226.56 2995.05 1156.4 3069.88 1127.56C3136.88 1101.75 3117.38 1127.56 3094.38 1162.56C3003.38 1196.06 2880.38 1259.56 2820.88 1340.06C2776.88 1373.56 2730.37 1537.45 2719.38 1642.06C2704.48 1783.83 2718.22 2115.89 2875.57 2129.06H2895.38C2888.54 2129.61 2881.93 2129.6 2875.57 2129.06H2331.88C2455.38 2129.06 2519.8 1805.43 2495.88 1642.06C2472.38 1481.56 2468.88 1485.06 2426.38 1393.56C2383.88 1302.06 2169.88 1188.06 2129.38 1170.56C2096.98 1156.56 2102.88 1136.06 2109.88 1127.56C2209.55 1165.73 2418.18 1245.56 2455.38 1259.56C2492.58 1273.56 2514.88 1241.06 2521.38 1223.06C2522.71 1167.4 2524.58 1049.86 2521.38 1025.06C2518.18 1000.26 2476.05 974.398 2455.38 964.564C2435.88 973.064 2391.88 992.764 2371.88 1003.56Z"
        />
      </svg>
    </div>
  )
}