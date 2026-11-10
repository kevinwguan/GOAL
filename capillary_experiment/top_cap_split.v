module top (gate_p, gate_n, drn_p_0, drn_p_1, drn_p_2, drn_p_3, drn_n_0, drn_n_1, drn_n_2, drn_n_3, tail_0, tail_1, tail_2, tail_3, tail_4, tail_5, tail_6, tail_7, bulk);
  input  gate_p, gate_n;
  output drn_p_0, drn_p_1, drn_p_2, drn_p_3, drn_n_0, drn_n_1, drn_n_2, drn_n_3;
  inout  tail_0, tail_1, tail_2, tail_3, tail_4, tail_5, tail_6, tail_7, bulk;

  diffpair_nmos_4f u0 (
    .gate_p(gate_p),
    .gate_n(gate_n),
    .drn_p_0(drn_p_0),
    .drn_p_1(drn_p_1),
    .drn_p_2(drn_p_2),
    .drn_p_3(drn_p_3),
    .drn_n_0(drn_n_0),
    .drn_n_1(drn_n_1),
    .drn_n_2(drn_n_2),
    .drn_n_3(drn_n_3),
    .tail_0(tail_0),
    .tail_1(tail_1),
    .tail_2(tail_2),
    .tail_3(tail_3),
    .tail_4(tail_4),
    .tail_5(tail_5),
    .tail_6(tail_6),
    .tail_7(tail_7),
    .bulk(bulk)
  );
endmodule
