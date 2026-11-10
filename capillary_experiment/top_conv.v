module top (gate_p, gate_n, drn_p, drn_n, tail, bulk);
  input  gate_p, gate_n;
  output drn_p, drn_n;
  inout  tail, bulk;

  diffpair_nmos_4f u0 (
    .gate_p(gate_p),
    .gate_n(gate_n),
    .drn_p(drn_p),
    .drn_n(drn_n),
    .tail(tail),
    .bulk(bulk)
  );
endmodule
