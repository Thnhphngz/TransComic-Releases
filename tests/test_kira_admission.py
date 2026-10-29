from transcomic.kira_admission import CohortAdmission


def test_nine_of_ten_and_last_short_cohort():
    order=[str(i) for i in range(23)];gate=CohortAdmission(order)
    assert gate.refresh([],order,[])==order[:10]
    assert gate.refresh(order[:1],order,order[1:10])==order[1:10]
    assert gate.frontier==0
    active=gate.refresh(order[:9],order,[order[9]])
    assert active==order[9:19] and gate.frontier==1
    active=gate.refresh(order[:10]+order[10:19],order,[])
    assert active==order[19:] and gate.frontier==2
    assert gate.refresh(order,[],[])==[]


def test_park_bounded_and_old_file_restores_before_new():
    order=[str(i) for i in range(100)];gate=CohortAdmission(order)
    gate.refresh([],order,[])
    assert gate.refresh([],[],[],can_expand=False)==order[:10]
    assert gate.refresh([],[],[],can_expand=True)==order[10:20]
    assert gate.parked==set(order[:10]) and len(gate.opened)==20
    gate.refresh([],[],[],can_expand=True)
    assert len(gate.opened)==20 and len(gate.parked)==10
    active=gate.refresh([],[order[0]],[],can_expand=True)
    assert order[0] in active and len(gate.parked)<=10 and len(active)<=10
    assert len(gate.opened)==20


def test_no_yield_of_inflight_and_bounded_priority_fairness():
    order=[str(i) for i in range(30)];gate=CohortAdmission(order)
    gate.refresh([],order,[]);gate.refresh([],[],order[:10])
    assert gate.active==set(order[:10]) and not gate.parked
    choices=[gate.choose(order,{v:100 if v=='9' else 1 for v in order[:10]}) for _ in range(30)]
    assert set(choices)==set(order[:10])


def test_resume_order_and_completed_certificate_are_not_trusted_blindly():
    order=[str(i) for i in range(12)];gate=CohortAdmission(order)
    gate.refresh([],order,[]);gate.refresh(order[:9],order,[])
    restored=CohortAdmission(order,gate.snapshot())
    restored.refresh(order[:9],order,[])
    assert restored.snapshot()==gate.snapshot()
    invalid=CohortAdmission(list(reversed(order)),gate.snapshot())
    assert not invalid.opened and invalid.frontier==0
