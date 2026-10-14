#include <cmath>
#include <cstdlib>
#include <iomanip>
#include <iostream>
#include <stdexcept>
#include <string>

#include "CVOde_Cell.hpp"
#include "cvode_function.h"

namespace {
double number(const char* value, const char* name) {
    char* end = nullptr;
    const double parsed = std::strtod(value, &end);
    if (end == value || *end != '\0' || !std::isfinite(parsed)) {
        throw std::invalid_argument(std::string("invalid ") + name);
    }
    return parsed;
}

int integer(const char* value, const char* name) {
    const double parsed = number(value, name);
    if (parsed != std::floor(parsed)) {
        throw std::invalid_argument(std::string("invalid ") + name);
    }
    return static_cast<int>(parsed);
}

void apply_scales(HAM_Signalling& cell, int argc, char** argv, int first) {
    if (argc == first) {
        return;
    }
    if (argc != first + 12) {
        throw std::invalid_argument("expected either zero or twelve current scales");
    }
    auto& p = cell.cell_para;
    p.INa_Scale = number(argv[first + 0], "g_Na scale");
    p.INaL_Scale = number(argv[first + 1], "g_NaL scale");
    p.Itof_Scale = number(argv[first + 2], "g_to scale");
    p.IKur_Scale = number(argv[first + 3], "g_Kur scale");
    p.IK2p_Scale = number(argv[first + 4], "g_K2P scale");
    p.IKr_Scale = number(argv[first + 5], "g_Kr scale");
    p.IKs_Scale = number(argv[first + 6], "g_Ks scale");
    p.IK1_Scale = number(argv[first + 7], "g_K1 scale");
    p.ISK_Scale = number(argv[first + 8], "g_SK scale");
    p.ICaL_Scale = number(argv[first + 9], "g_CaL scale");
    p.INaK_Scale = number(argv[first + 10], "g_NaK scale");
    p.INCX_Scale = number(argv[first + 11], "g_NaCa scale");
}
}  // namespace

int main(int argc, char** argv) {
    // bcl_ms, prepace_beats, duration_ms, AF, ISO_uM, CaMKII_inhibition,
    // CaMKII_double, initial_conditions, followed by optional scales.
    if (argc != 9 && argc != 21) {
        std::cerr << "usage: ni_driver bcl prepace duration AF ISO CaMKII_inhibition "
                     "CaMKII_double initial_conditions [12 scales]\n";
        return 2;
    }
    try {
        const double bcl = number(argv[1], "BCL");
        const int prepace_beats = integer(argv[2], "prepace beats");
        const double duration = number(argv[3], "duration");
        const int af = integer(argv[4], "AF");
        const double iso = number(argv[5], "ISO");
        const int camkii_inhibition = integer(argv[6], "CaMKII inhibition");
        const int camkii_double = integer(argv[7], "CaMKII double");
        if (bcl < 100.0 || bcl > 10000.0 || prepace_beats < 0 ||
            prepace_beats > 100 || duration <= 0.0 || duration > 20000.0 ||
            (af != 0 && af != 1) || iso < 0.0 || iso > 1.0 ||
            (camkii_inhibition != 0 && camkii_inhibition != 1) ||
            (camkii_double != 0 && camkii_double != 1)) {
            throw std::invalid_argument("argument outside validated bounds");
        }

        CVOde_Cell wrapper(184, 1.0, f, false);
        wrapper.cell.BCL = bcl;
        wrapper.cell.assign_AF_ISO_CaMKII_para(af, iso, camkii_double != 0);
        wrapper.cell.cell_para.CaMKII_Inhibition = camkii_inhibition;
        wrapper.read_initial_condition(argv[8]);
        apply_scales(wrapper.cell, argc, argv, 9);

        const double warmup = prepace_beats * bcl;
        const double total = warmup + duration;
        constexpr double step = 0.1;
        constexpr double output_interval = 0.2;
        double next_output = warmup;

        std::cout << "time_ms,voltage_mv,calcium_mm,INa,INaL,Ito,IKur,IK2P,IKr,IKs,IK1,ISK,ICaL,INaK,INaCa\n";
        std::cout << std::setprecision(12);
        bool pre_sample_written = false;
        if (warmup == 0.0) {
            // Preserve the supplied steady-state sample immediately before the
            // t=0 stimulus so beat metrics have a real diastolic value.
            std::cout << -step << ',' << Ith(wrapper.cvode.y, 39) << ','
                      << Ith(wrapper.cvode.y, 38)
                      << ",0,0,0,0,0,0,0,0,0,0,0,0\n";
            pre_sample_written = true;
        }
        for (double target = step; target <= total + 0.5 * step; target += step) {
            wrapper.solve_single_time_step(target, step);
            auto& ecc = wrapper.cell.ECC_Module;
            ecc.V = Ith(wrapper.cvode.y, 39);
            const double cai = Ith(wrapper.cvode.y, 38);
            if (!pre_sample_written && target + 1e-9 >= warmup - step) {
                std::cout << -step << ',' << ecc.V << ',' << cai << ','
                          << ecc.I_Na << ',' << ecc.I_NaL << ',' << ecc.I_to << ','
                          << ecc.I_kur << ',' << ecc.I_k2p << ',' << ecc.I_kr << ','
                          << ecc.I_ks << ',' << ecc.I_ki << ',' << ecc.I_sk << ','
                          << ecc.I_Ca << ',' << ecc.I_nak << ',' << ecc.I_ncx << '\n';
                pre_sample_written = true;
            }
            if (target + 1e-9 < next_output) {
                continue;
            }
            std::cout << (target - warmup) << ',' << ecc.V << ',' << cai << ','
                      << ecc.I_Na << ',' << ecc.I_NaL << ',' << ecc.I_to << ','
                      << ecc.I_kur << ',' << ecc.I_k2p << ',' << ecc.I_kr << ','
                      << ecc.I_ks << ',' << ecc.I_ki << ',' << ecc.I_sk << ','
                      << ecc.I_Ca << ',' << ecc.I_nak << ',' << ecc.I_ncx << '\n';
            next_output += output_interval;
        }
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 2;
    }
    return 0;
}
