//! Canonical float rendering, identical in every port (SPEC section 4).
//!
//! Digits are the shortest decimal that roundtrips to the same binary64;
//! each port obtains them from its platform's shortest formatter (Rust's
//! `{:e}`) and re-renders with the pinned presentation rules.

/// Render a finite binary64 per the pinned presentation rules:
/// - integral floats keep one fractional digit: `1.0`, `-0.0`
/// - exponential form iff the decimal exponent is `>= 21` or `<= -7`
/// - exponent always signed, no zero padding: `1e+21`, `1.5e-7`
pub fn render_float(f: f64) -> String {
    debug_assert!(f.is_finite());
    if f == 0.0 {
        return if f.is_sign_negative() { "-0.0" } else { "0.0" }.to_string();
    }
    let sign = if f.is_sign_negative() { "-" } else { "" };
    let (digits, exp) = shortest_digits(f);
    let n = digits.len() as i32;
    if exp >= 21 || exp <= -7 {
        let mant = if n > 1 {
            format!("{}.{}", &digits[..1], &digits[1..])
        } else {
            digits.clone()
        };
        let esign = if exp >= 0 { '+' } else { '-' };
        return format!("{}{}e{}{}", sign, mant, esign, exp.abs());
    }
    if exp >= n - 1 {
        let zeros = "0".repeat((exp - (n - 1)) as usize);
        return format!("{}{}{}.0", sign, digits, zeros);
    }
    if exp >= 0 {
        let e = exp as usize;
        format!("{}{}.{}", sign, &digits[..e + 1], &digits[e + 1..])
    } else {
        format!("{}0.{}{}", sign, "0".repeat((-exp - 1) as usize), digits)
    }
}

/// Shortest-roundtrip digits for a finite non-zero `|f|` plus the decimal
/// exponent such that `value == 0.digits * 10^(exp+1)`.
fn shortest_digits(f: f64) -> (String, i32) {
    // Rust's LowerExp for f64 produces the shortest roundtrip form.
    let s = format!("{:e}", f.abs());
    let (mant, exp_s) = s.split_once('e').expect("LowerExp always emits 'e'");
    let exp: i32 = exp_s.parse().expect("valid exponent");
    let mut digits: String = mant.chars().filter(|c| *c != '.').collect();
    while digits.ends_with('0') {
        digits.pop();
    }
    // strip leading zeros (defensive; Rust never emits them here)
    let trimmed = digits.trim_start_matches('0');
    let lead = digits.len() - trimmed.len();
    if trimmed.is_empty() {
        return ("0".to_string(), 0);
    }
    (trimmed.to_string(), exp - lead as i32)
}

#[cfg(test)]
mod tests {
    use super::render_float;

    #[test]
    fn pinned_presentation() {
        assert_eq!(render_float(1.0), "1.0");
        assert_eq!(render_float(0.1), "0.1");
        assert_eq!(render_float(1e21), "1e+21");
        assert_eq!(render_float(1e20), "100000000000000000000.0");
        assert_eq!(render_float(1.5e-7), "1.5e-7");
        assert_eq!(render_float(5e-324), "5e-324");
        assert_eq!(render_float(-0.0), "-0.0");
        assert_eq!(render_float(123.456), "123.456");
        assert_eq!(render_float(2.5e-10), "2.5e-10");
        assert_eq!(render_float(1e-6), "0.000001");
        assert_eq!(render_float(9007199254740991.0), "9007199254740991.0");
    }
}
