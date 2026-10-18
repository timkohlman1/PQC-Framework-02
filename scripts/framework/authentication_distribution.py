"""Boxplots of pinned authentication run observations; no cross-batch pooling."""
import csv
import json
import math
from pathlib import Path
import numpy as np
from framework.run_evidence import sha256_file

NULL = {"", r"\N", r"\\N"}


def box(values):
    if not values or any(not math.isfinite(v) or v < 0 for v in values):
        raise ValueError("finite nonnegative latency values required")
    q1, med, q3 = (float(v) for v in np.quantile(values, [.25,.5,.75], method="linear"))
    inside=[v for v in values if q1-1.5*(q3-q1)<=v<=q3+1.5*(q3-q1)]
    return dict(q1=q1,median=med,q3=q3,lower=min(inside),upper=max(inside),
                minimum=min(values),maximum=max(values),n=len(values))


def publish(report, output, selection="authentication"):
    report,output=Path(report),Path(output)
    if output.exists():
        raise ValueError("choose a fresh distribution output")
    if not selection or any(c not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_-" for c in selection):
        raise ValueError("invalid selection")
    checks=json.loads((report/"checksums.json").read_text());inputs={}
    def read(kind):
        name=f"data-{selection}-{kind}.csv";path=report/name;digest=sha256_file(path)
        if checks.get(name)!=digest:
            raise ValueError("published input checksum mismatch")
        inputs[str(path)]=digest
        return list(csv.DictReader(path.open()))
    observations=read("observations");inventory=read("inventory");published=read("distributions")
    included={r["run_key"]:r for r in inventory if r["exclusion_reason"] in NULL
        and r["selected_input_status"]=="verified" and r["execution_outcome"]=="completed"}
    groups={}
    seen=set();points=[]
    for r in observations:
        if r["metric"]!="tls_handshake" or r["validity"]!="valid" or r["exclusion_reason"] not in NULL:
            continue
        inv=included.get(r["run_key"])
        if inv is None:
            continue
        if inv["tls_kex"]!="secp256r1" or r["condition"]!=inv["condition"]:
            raise ValueError("authentication plot requires fixed P-256 and matching condition identities")
        if r["unit"]!="us" or r["scope"]!="framework_run" or r["operation_outcome"]!="success":
            raise ValueError("unsupported handshake observation boundary")
        if r["run_key"] in seen:
            raise ValueError("reduce repeated handshakes per run before this plot")
        seen.add(r["run_key"])
        key=(inv["auth_mode"],inv["tls_auth"]);value=float(r["value_us"])/1000
        groups.setdefault(key,[]).append(value)
        points.append(dict(condition=r["condition"],auth_mode=key[0],tls_auth=key[1],
            run_key=r["run_key"],observation_id=r["observation_id"],latency_ms=value))
    algorithms=["rsa3072","ecdsa-p256","ecdsa-p384","mldsa65"]
    labels=["RSA-3072","ECDSA P-256","ECDSA P-384","ML-DSA-65"]
    expected={(mode,alg) for mode in ("server","mutual") for alg in algorithms}
    if set(groups)!=expected:
        raise ValueError("complete four-family server/mutual selection required")
    stats={key:box(vals) for key,vals in groups.items()}
    for (mode,alg),v in stats.items():
        rows=[r for r in published if r["condition"]==f"tls_auth={alg}; auth_mode={mode}" and r["metric"]=="tls_handshake"]
        if len(rows)!=1 or int(rows[0]["n_runs"])!=v["n"] or any(abs(float(rows[0][name])/1000-v[name])>1e-7 for name in ("q1","median","q3")):
            raise ValueError("run points do not reproduce the published distribution")
    if any(v["median"]<=0 for v in stats.values()):
        raise ValueError("normalised variability requires a positive median")
    deviation=max(abs(100*(x/stats[k]["median"]-1)) for k,values in groups.items() for x in values)
    bound=max(5,math.ceil(deviation/5)*5)
    code=r"""\begin{figure}[!htbp]
\centering
\begingroup
\begin{tikzpicture}
\begin{groupplot}[group style={group size=2 by 1,horizontal sep=1.1cm},
width=.33\linewidth,height=5cm,scale only axis,ytick={1,2,3,4},ymin=.5,ymax=4.5,
tick label style={font=\scriptsize},title style={font=\small},label style={font=\scriptsize},
xlabel={Deviation from condition median (\%)},xmajorgrids=true,grid style={gray!20},scaled ticks=false]
"""
    for mode in ("server","mutual"):
        ticks=",".join("{"+x+"}" for x in reversed(labels)) if mode=="server" else "{},{},{},{}"
        code+=r"\nextgroupplot[title={"+mode.title()+" authentication},yticklabels={"+ticks+"},"+f"xmin={-bound},xmax={bound}"+"]\n"
        code+=r"\draw[dashed,gray] (axis cs:0,.5) -- (axis cs:0,4.5);"+"\n"
        for i,alg in enumerate(algorithms):
            key=(mode,alg);v=stats[key];y=4-i
            if v["median"]<=0:
                raise ValueError("normalised variability requires a positive median")
            relative=lambda x:100*(x/v["median"]-1)
            color="orange!80!black" if alg=="mldsa65" else "blue!65!black"
            opts=",".join(name+"="+f"{relative(v[field]):.6f}" for name,field in
                [("lower whisker","lower"),("lower quartile","q1"),("median","median"),("upper quartile","q3"),("upper whisker","upper")])
            code+=r"\addplot+[boxplot prepared={draw position="+str(y)+","+opts+r"},draw="+color+r",fill="+color+r"!15,mark=none] coordinates {};"+"\n"
            coords=" ".join(f"({relative(x):.6f},{y+((j%7)-3)*.017:.3f})" for j,x in enumerate(groups[key]))
            code+=r"\addplot[only marks,mark=*,mark size=.7pt,opacity=.5,color="+color+"] coordinates {"+coords+"};\n"
    code+=r"""\end{groupplot}\end{tikzpicture}
\endgroup
\caption{Relative handshake variability with P-256 key establishment fixed.
Each observation is $100(t/\widetilde{t}-1)$, using its condition median;
both panels have the same scale and median at zero. Blue is classical authentication;
orange is ML-DSA-65. Boxes show Q1--Q3; whiskers use 1.5 IQR and all eligible run
observations remain visible (@@COUNTS@@ per condition). The separate signing follow-up is not pooled.}
\label{fig:authentication-variability}
\end{figure}
"""
    # Fixed attempts and metric eligibility are distinct; retain every eligible
    # point and state its actual count instead of requiring all attempts to pass.
    counts = [v["n"] for v in stats.values()]
    count_label = str(min(counts)) if min(counts) == max(counts) else f"{min(counts)}--{max(counts)}"
    code = code.replace("@@COUNTS@@", count_label)
    output.mkdir(parents=True)
    (output/"authentication-variability.tex").write_text(code)
    for name,rows in [("authentication-run-latencies.csv",points),
                     ("authentication-boxplots.csv",[dict(auth_mode=k[0],tls_auth=k[1],**v) for k,v in stats.items()])]:
        with (output/name).open("w") as stream:
            writer=csv.DictWriter(stream,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
    provenance=dict(schema="pqc-authentication-distribution",version=2,report=str(report),inputs=inputs,
        generator_sha256=sha256_file(Path(__file__)),files={p.name:sha256_file(p) for p in output.iterdir()})
    (output/"authentication-variability-provenance.json").write_text(json.dumps(provenance,indent=2)+"\n")
    return provenance
