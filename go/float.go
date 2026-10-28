package lombokserde

import (
	"fmt"
	"math"
	"strconv"
	"strings"
)

// RenderFloat renders a finite binary64 per the pinned presentation rules
// (SPEC section 4): shortest-roundtrip digits obtained from the platform
// formatter (strconv with precision -1), re-rendered with fixed rules:
//   - integral floats keep one fractional digit: 1 -> "1.0", -0.0 -> "-0.0"
//   - exponential form iff the decimal exponent is >= 21 or <= -7
//   - exponent always signed, no zero padding: "1e+21", "1.5e-7"
func RenderFloat(fl float64) string {
	if fl == 0 {
		if math.Signbit(fl) {
			return "-0.0"
		}
		return "0.0"
	}
	sign := ""
	if math.Signbit(fl) {
		sign = "-"
	}
	digits, exp := shortestDigits(math.Abs(fl))
	n := len(digits)
	if exp >= 21 || exp <= -7 {
		var mant string
		if n > 1 {
			mant = digits[:1] + "." + digits[1:]
		} else {
			mant = digits
		}
		esign := "+"
		if exp < 0 {
			esign = "-"
		}
		ae := exp
		if ae < 0 {
			ae = -ae
		}
		return fmt.Sprintf("%s%se%s%d", sign, mant, esign, ae)
	}
	if exp >= n-1 {
		return sign + digits + strings.Repeat("0", exp-(n-1)) + ".0"
	}
	if exp >= 0 {
		return sign + digits[:exp+1] + "." + digits[exp+1:]
	}
	return sign + "0." + strings.Repeat("0", -exp-1) + digits
}

// shortestDigits returns the shortest-roundtrip digits of |fl| plus the
// decimal exponent of the first digit (value = 0.digits * 10^(exp+1)).
func shortestDigits(fl float64) (string, int) {
	s := strconv.FormatFloat(fl, 'e', -1, 64)
	// forms: "1.5e+300", "1e+21", "5e-324", "1e-07"
	mant := s
	exp := 0
	if idx := strings.IndexByte(s, 'e'); idx >= 0 {
		mant = s[:idx]
		e, err := strconv.Atoi(s[idx+1:])
		if err != nil {
			return "0", 0
		}
		exp = e
	}
	mant = strings.Replace(mant, ".", "", 1)
	// strip leading zeros (defensive)
	first := 0
	for first < len(mant) && mant[first] == '0' {
		first++
	}
	mant = mant[first:]
	// strip trailing zeros
	end := len(mant)
	for end > 0 && mant[end-1] == '0' {
		end--
	}
	if end == 0 {
		return "0", 0
	}
	return mant[:end], exp
}
