module top (gate_p, gate_n, drn_p, drn_n, tail, bulk);
  input  gate_p, gate_n;
  output drn_p, drn_n;
  inout  tail, bulk;

  diffpair_nmos_4f u0 (
    .gate_p(gate_p),
    .gate_n(gate_n),
    .drn_p_0(drn_p),
    .drn_p_1(drn_p),
    .drn_p_2(drn_p),
    .drn_p_3(drn_p),
    .drn_n_0(drn_n),
    .drn_n_1(drn_n),
    .drn_n_2(drn_n),
    .drn_n_3(drn_n),
    .tail_0(tail),
    .tail_1(tail),
    .tail_2(tail),
    .tail_3(tail),
    .tail_4(tail),
    .tail_5(tail),
    .tail_6(tail),
    .tail_7(tail),
    .bulk(bulk)
  );
endmodule
