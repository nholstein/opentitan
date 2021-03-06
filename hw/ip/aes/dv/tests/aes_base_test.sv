// Copyright lowRISC contributors.
// Licensed under the Apache License, Version 2.0, see LICENSE for details.
// SPDX-License-Identifier: Apache-2.0

class aes_base_test extends cip_base_test #(
    .ENV_T(aes_env),
    .CFG_T(aes_env_cfg)
  );
  `uvm_component_utils(aes_base_test)
  `uvm_component_new

  // the base class dv_base_test creates the following instances:
  // aes_env_cfg: cfg
  // aes_env:     env

  // the base class also looks up UVM_TEST_SEQ plusarg to create and run that seq in
  // the run_phase; as such, nothing more needs to be done

//    function configure_knobs()
//      endfunction // configure_knobs


endclass : aes_base_test

