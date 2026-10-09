#pragma once

// The pinned Ni 2023 source targets SUNDIALS 5.7. SUNDIALS 6 adds a
// SUNContext argument to constructors. This header is force-included after
// first loading the SUNDIALS declarations, then adapts only the old call
// sites. The upstream checkout remains byte-for-byte unchanged.
#include <cvode/cvode.h>
#include <nvector/nvector_serial.h>
#include <sunlinsol/sunlinsol_dense.h>
#include <sunmatrix/sunmatrix_dense.h>
#include <sundials/sundials_context.h>

inline SUNContext ni_sundials_context() {
    static SUNContext context = [] {
        SUNContext value = nullptr;
        if (SUNContext_Create(nullptr, &value) != 0) {
            return static_cast<SUNContext>(nullptr);
        }
        return value;
    }();
    return context;
}

#define N_VNew_Serial(length) N_VNew_Serial((length), ni_sundials_context())
#define CVodeCreate(lmm) CVodeCreate((lmm), ni_sundials_context())
#define SUNDenseMatrix(rows, cols) SUNDenseMatrix((rows), (cols), ni_sundials_context())
#define SUNLinSol_Dense(vector, matrix) SUNLinSol_Dense((vector), (matrix), ni_sundials_context())
